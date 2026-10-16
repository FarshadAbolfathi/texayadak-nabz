"""تطبیق کد سایت با ایساکو (وقتی ایساکو دو رقم آخر کد را حذف می‌کند)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from nabz.codematch import resolve, short_code_key, suggest
from nabz.config import CredentialStore, MemoryBackend, WooCredentials
from nabz.db import Database
from nabz.engine import build_plan
from nabz.pricing import PriceRules
from nabz.sources.isaco_excel import IsacoItem
from nabz.stock import StockRules
from nabz.targets.woocommerce import WooProduct


def item(code, name="کالا", vat=10_000_000):
    return IsacoItem(code, name, "پژو ۲۰۶", "عدد", 1, retail=vat, vat=vat, wholesale=vat)


# مثل لیست واقعی: ۱۲۳۰۲۰۰۵ سه کالای متفاوت را می‌پوشاند
LIST = {c: item(c, f"کالای {c}") for c in (
    "1230200505", "1230200598", "1230200599", "1230100499")}


class TestSuggest:
    def test_exact_code_needs_no_suggestion(self):
        assert suggest("1230200599", LIST) == []

    def test_short_code_suggested_first(self):
        lst = dict(LIST)
        del lst["1230200599"]
        lst["0012302005"] = item("0012302005", "مقاومت بخاری (کد کوتاه)")
        reasons = [(c.item.code, c.reason) for c in suggest("1230200599", lst)]
        assert reasons[0] == ("0012302005", "short")
        # هم‌خانواده‌ها هم هستند ولی بعد از کد کوتاه
        assert ("1230200505", "family") in reasons and ("1230200598", "family") in reasons

    def test_ambiguous_family_is_only_suggested_never_auto(self):
        lst = {c: v for c, v in LIST.items() if c != "1230200599"}
        cands = suggest("1230200599", lst)
        assert len(cands) == 2 and all(c.reason == "family" for c in cands)
        # بدون تأیید کارفرما هیچ قیمتی نمی‌آید
        assert resolve("1230200599", lst, {}) == (None, "")

    def test_short_key(self):
        assert short_code_key("1230200599") == "0012302005"


class TestResolveAndEngine:
    def test_mapping_used_only_when_exact_missing(self):
        lst = {"0012302005": item("0012302005")}
        assert resolve("1230200599", lst, {"1230200599": "0012302005"})[1] == "0012302005"
        lst["1230200599"] = item("1230200599")
        assert resolve("1230200599", lst, {"1230200599": "0012302005"})[1] == ""

    def test_engine_prices_mapped_product(self):
        lst = {"0012302005": item("0012302005", vat=13_600_000)}
        product = WooProduct(id=1, name="مقاومت", sku="1230200599", regular_price="1000000",
                             stock_quantity=1, stock_status="instock", manage_stock=True,
                             type="simple", status="publish")
        rules = PriceRules(markup_percent=Decimal("0"))
        no_map = build_plan([product], lst, {}, rules, StockRules(), update_stock=False)
        assert no_map.items[0].new_price is None
        mapped = build_plan([product], lst, {}, rules, StockRules(), update_stock=False,
                            code_map={"1230200599": "0012302005"})
        assert mapped.items[0].new_price == 1_360_000
        assert mapped.items[0].mapped_code == "0012302005"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def store():
    s = CredentialStore(backend=MemoryBackend())
    s.save_woo(WooCredentials(base_url="https://x.com", consumer_key="ck",
                              consumer_secret="cs"))
    return s


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    no = QMessageBox.StandardButton.No
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: no))


class TestDialog:
    def rows(self):
        lst = {"0012302005": item("0012302005", "مقاومت بخاری کوتاه"),
               "1230200505": item("1230200505", "هم‌خانواده")}
        product = WooProduct(id=1, name="مقاومت بخاری", sku="1230200599",
                             regular_price="", stock_quantity=1, stock_status="instock",
                             manage_stock=True, type="simple", status="publish")
        plan = build_plan([product], lst, {}, PriceRules(), StockRules(), update_stock=False)
        return [(plan.items[0], suggest("1230200599", lst))]

    def test_nothing_preselected(self, qapp):
        from nabz.ui.code_match_dialog import CodeMatchDialog
        dlg = CodeMatchDialog(self.rows(), PriceRules())
        assert dlg.selections() == {} and not dlg.ok.isEnabled()

    def test_pick_short_and_save(self, qapp):
        from nabz.ui.code_match_dialog import CodeMatchDialog
        dlg = CodeMatchDialog(self.rows(), PriceRules())
        dlg._select_short()
        assert dlg.selections() == {"1230200599": "0012302005"}
        assert dlg.table.item(0, dlg.C_NEW).text()          # قیمت با این تطبیق
        dlg._accept()
        assert dlg.chosen == {"1230200599": "0012302005"}


class TestSyncTabIntegration:
    def test_worker_result_with_isaco_and_match_button(self, qapp, db, store):
        from nabz.ui.tabs.sync import SyncTab
        lst = {"0012302005": item("0012302005")}
        product = WooProduct(id=1, name="مقاومت", sku="1230200599", regular_price="5",
                             stock_quantity=1, stock_status="instock", manage_stock=True,
                             type="simple", status="publish")
        plan = build_plan([product], lst, {}, PriceRules(), StockRules(), update_stock=False)
        tab = SyncTab(db, store)
        tab._on_compared((plan, True, False, 0, lst))          # شکل واقعی نتیجهٔ worker
        assert tab._isaco is lst
        btn = tab.table.cellWidget(0, tab.COL_APPLY)
        assert btn is not None and "تطبیق" in btn.text()

    def test_saved_match_is_persisted(self, qapp, db, store):
        from nabz.ui.tabs.sync import SyncTab
        tab = SyncTab(db, store)
        tab._save_matches({"1230200599": "0012302005"})
        assert db.get_code_map() == {"1230200599": "0012302005"}

    def test_fetch_button_still_downloads(self, qapp, db, store, monkeypatch):
        """clicked(bool) نباید به‌عنوان download=False برسد."""
        from nabz.ui.tabs.sync import SyncTab
        tab = SyncTab(db, store)
        calls = []
        monkeypatch.setattr(tab, "_try_browser_download", lambda: calls.append(1))
        monkeypatch.setattr(tab, "_run_worker", lambda *a, **k: None)
        tab.fetch_btn.click()
        assert calls == [1]
        tab._set_busy(False)
