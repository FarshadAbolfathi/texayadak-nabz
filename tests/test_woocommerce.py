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


class TestBatchOutcome:
    def test_merge_combines_results(self):
        a = BatchOutcome(updated=[1, 2], failed={3: "x"})
        b = BatchOutcome(updated=[4], failed={5: "y"})
        a.merge(b)
        assert a.updated == [1, 2, 4]
        assert a.failed == {3: "x", 5: "y"}
