"""تست کلاینت ووکامرس با یک session جعلی (بدون تماس واقعی با سایت)."""

import json

import pytest

from nabz.targets.woocommerce import (
    BatchOutcome,
    WooClient,
    WooConfig,
    WooError,
    WooProduct,
)


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else []
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeSession:
    """جای requests.Session را می‌گیرد و پاسخ‌های از پیش‌تعیین‌شده می‌دهد."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.auth = None
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"درخواست پیش‌بینی‌نشده: {method} {url}")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def config():
    return WooConfig(
        base_url="https://texayadak.com/",
        consumer_key="ck_test",
        consumer_secret="cs_test",
        retries=3,
        backoff=0,  # بدون مکث در تست
    )


class TestFetchProducts:
    def test_reads_a_single_page(self, config):
        page = [
            {"id": 4154, "name": "مغزی پمپ", "sku": "", "regular_price": "3000000",
             "stock_quantity": None, "manage_stock": False,
             "stock_status": "instock", "type": "simple", "status": "publish"},
            {"id": 3604, "name": "سنسور", "sku": "921900804", "regular_price": "",
             "stock_quantity": 3, "manage_stock": True,
             "stock_status": "instock", "type": "simple", "status": "publish"},
        ]
        session = FakeSession([FakeResponse(body=page, headers={"X-WP-TotalPages": "1"})])
        client = WooClient(config, session=session)
        products = client.fetch_products()
        assert len(products) == 2
        assert products[1].sku == "921900804"
        assert products[1].stock_quantity == 3

    def test_follows_pagination(self, config):
        p1 = [{"id": i, "name": "x", "sku": str(i), "regular_price": "1",
               "stock_quantity": 1, "manage_stock": True,
               "stock_status": "instock", "type": "simple", "status": "publish"}
              for i in range(100)]
        p2 = [{"id": 100, "name": "y", "sku": "100", "regular_price": "1",
               "stock_quantity": 1, "manage_stock": True,
               "stock_status": "instock", "type": "simple", "status": "publish"}]
        session = FakeSession([
            FakeResponse(body=p1, headers={"X-WP-TotalPages": "2"}),
            FakeResponse(body=p2, headers={"X-WP-TotalPages": "2"}),
        ])
        client = WooClient(config, session=session)
        assert len(client.fetch_products()) == 101

    def test_price_toman_parses_regular_price(self):
        product = WooProduct(
            id=1, name="x", sku="1", regular_price="7934000",
            stock_quantity=2, stock_status="instock", manage_stock=True,
            type="simple", status="publish",
        )
        assert product.price_toman == 7_934_000

    def test_price_toman_none_when_empty(self):
        product = WooProduct(
            id=1, name="x", sku="1", regular_price="",
            stock_quantity=2, stock_status="instock", manage_stock=True,
            type="simple", status="publish",
        )
        assert product.price_toman is None


class TestCounts:
    def test_reads_total_header(self, config):
        session = FakeSession([FakeResponse(headers={"X-WP-Total": "292"})])
        client = WooClient(config, session=session)
        assert client.count_products() == 292


class TestBatchUpdate:
    def test_splits_into_chunks_of_100(self, config):
        updates = [{"id": i, "regular_price": "1000"} for i in range(1, 251)]
        responses = [
            FakeResponse(body={"update": [{"id": u["id"]} for u in updates[0:100]]}),
            FakeResponse(body={"update": [{"id": u["id"]} for u in updates[100:200]]}),
            FakeResponse(body={"update": [{"id": u["id"]} for u in updates[200:250]]}),
        ]
        session = FakeSession(responses)
        client = WooClient(config, session=session)
        outcome = client.batch_update(updates)
        assert len(outcome.updated) == 250
        assert outcome.ok
        # سه درخواست batch زده شده، نه ۲۵۰ تا
        batch_calls = [c for c in session.calls if "products/batch" in c[1]]
        assert len(batch_calls) == 3

    def test_reports_products_that_did_not_come_back(self, config):
        updates = [{"id": 1, "regular_price": "1"}, {"id": 2, "regular_price": "2"}]
        session = FakeSession([FakeResponse(body={"update": [{"id": 1}]})])
        client = WooClient(config, session=session)
        outcome = client.batch_update(updates)
        assert outcome.updated == [1]
        assert 2 in outcome.failed
        assert not outcome.ok


class TestRetry:
    def test_retries_on_500_then_succeeds(self, config):
        session = FakeSession([
            FakeResponse(status=500),
            FakeResponse(status=500),
            FakeResponse(body=[], headers={"X-WP-TotalPages": "1"}),
        ])
        client = WooClient(config, session=session)
        assert client.fetch_products() == []
        assert len(session.calls) == 3

    def test_raises_after_exhausting_retries(self, config):
        session = FakeSession([FakeResponse(status=503)] * 3)
        client = WooClient(config, session=session)
        with pytest.raises(WooError, match="تلاش"):
            client.fetch_products()

    def test_does_not_retry_on_4xx(self, config):
        session = FakeSession([FakeResponse(status=401, body={"m": "unauthorized"})])
        client = WooClient(config, session=session)
        with pytest.raises(WooError, match="401"):
            client.fetch_products()
        assert len(session.calls) == 1


class TestServerCompat:
    """سازگاری با سرورهایی که درخواست غیرمرورگری را ۴۰۳ می‌کنند."""

    def test_browser_user_agent_is_set(self, config):
        session = FakeSession([])
        client = WooClient(config, session=session)
        assert "Mozilla" in session.headers.get("User-Agent", "")

    def test_auth_also_sent_as_query_params(self, config):
        session = FakeSession([FakeResponse(headers={"X-WP-Total": "5"})])
        client = WooClient(config, session=session)
        client.count_products()
        _, _, kwargs = session.calls[0]
        assert kwargs["params"]["consumer_key"] == "ck_test"
        assert kwargs["params"]["consumer_secret"] == "cs_test"


class TestBatchOutcome:
    def test_merge_combines_results(self):
        a = BatchOutcome(updated=[1, 2], failed={3: "x"})
        b = BatchOutcome(updated=[4], failed={5: "y"})
        a.merge(b)
        assert a.updated == [1, 2, 4]
        assert a.failed == {3: "x", 5: "y"}


class TestProductDetails:
    def test_parses_categories_images_and_sale_price(self, config):
        page = [{"id": 7, "name": "سپر", "sku": "50102699", "regular_price": "900",
                 "sale_price": "800", "stock_quantity": 2, "manage_stock": True,
                 "stock_status": "instock", "type": "simple", "status": "publish",
                 "categories": [{"id": 3, "name": "پژو ۴۰۵"}],
                 "images": [{"id": 55, "src": "https://x/a.jpg"}, {"id": 56, "src": "b"}]}]
        session = FakeSession([FakeResponse(body=page, headers={"X-WP-TotalPages": "1"})])
        (p,) = WooClient(config, session=session).fetch_products()
        assert p.sale_price == "800"
        assert p.category_ids == [3] and p.category_names == "پژو ۴۰۵"
        assert p.image_url == "https://x/a.jpg" and p.image_id == 55
        assert p.gallery_ids == (56,)


class TestBatchErrors:
    def test_item_level_error_is_reported_as_failure(self, config):
        body = {"update": [{"id": 1}, {"id": 2, "error": {"code": "x", "message": "SKU تکراری"}}]}
        session = FakeSession([FakeResponse(body=body)])
        outcome = WooClient(config, session=session).batch_update(
            [{"id": 1, "sku": "a"}, {"id": 2, "sku": "a"}])
        assert outcome.updated == [1]
        assert outcome.failed == {2: "SKU تکراری"}


class TestCreate:
    def test_batch_create_maps_indexes(self, config):
        body = {"create": [{"id": 101}, {"id": 0, "error": {"message": "نامعتبر"}}]}
        session = FakeSession([FakeResponse(body=body)])
        created, failed = WooClient(config, session=session).batch_create(
            [{"name": "a"}, {"name": "b"}])
        assert created == {0: 101}
        assert failed == {1: "نامعتبر"}
        _, url, kwargs = session.calls[0]
        assert url.endswith("products/batch") and "create" in kwargs["json"]

    def test_trash_uses_status_update(self, config):
        session = FakeSession([FakeResponse(body={"update": [{"id": 5}]})])
        outcome = WooClient(config, session=session).batch_delete([5])
        assert outcome.updated == [5]
        assert session.calls[0][2]["json"] == {"update": [{"id": 5, "status": "trash"}]}


class TestCategories:
    def test_fetch_categories_unescapes_names(self, config):
        body = [{"id": 1, "name": "ترمز &amp; کلاچ", "parent": 0, "slug": "b", "count": 4}]
        session = FakeSession([FakeResponse(body=body, headers={"X-WP-TotalPages": "1"})])
        (cat,) = WooClient(config, session=session).fetch_categories()
        assert cat.name == "ترمز & کلاچ" and cat.count == 4


class TestOrders:
    def test_list_orders_returns_totals(self, config):
        session = FakeSession([FakeResponse(
            body=[{"id": 9}], headers={"X-WP-Total": "120", "X-WP-TotalPages": "3"})])
        orders, total, pages = WooClient(config, session=session).list_orders(
            status="processing", search="0912", page=2)
        assert orders == [{"id": 9}] and total == 120 and pages == 3
        params = session.calls[0][2]["params"]
        assert params["status"] == "processing" and params["search"] == "0912"
        assert params["page"] == 2

    def test_any_status_is_not_sent(self, config):
        session = FakeSession([FakeResponse(body=[])])
        WooClient(config, session=session).list_orders(status="any")
        assert "status" not in session.calls[0][2]["params"]

    def test_update_order_and_note(self, config):
        session = FakeSession([FakeResponse(body={"id": 9, "status": "completed"}),
                               FakeResponse(body={"id": 1})])
        client = WooClient(config, session=session)
        assert client.update_order(9, {"status": "completed"})["status"] == "completed"
        client.add_order_note(9, "ارسال شد", customer_note=True)
        method, url, kwargs = session.calls[1]
        assert method == "POST" and url.endswith("orders/9/notes")
        assert kwargs["json"] == {"note": "ارسال شد", "customer_note": True}


class TestMedia:
    def test_upload_requires_app_password(self, config, tmp_path):
        client = WooClient(config, session=FakeSession([]))
        with pytest.raises(WooError, match="رمز برنامه"):
            client.upload_media(str(tmp_path / "a.jpg"))
