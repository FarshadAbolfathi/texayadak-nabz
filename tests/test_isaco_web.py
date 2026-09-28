"""تست کلاینت وب ایساکو با سرور جعلی.

پاسخ‌های سرور را با همان طرح رمزنگاری واقعی تولید می‌کنیم (کلید آزمایشی)
تا مسیر کامل «رمز کردن درخواست → رمزگشایی پاسخ» تست شود، بدون تماس
واقعی با ایساکو.
"""

import base64
import json
import time

import pytest
from Crypto.PublicKey import RSA

from nabz.sources.isaco_crypto import decrypt_response, encrypt_request
from nabz.sources.isaco_web import (
    IsacoClient,
    IsacoCredentials,
    IsacoLoginError,
    _decode_jwt_exp,
    digits_only_version,
)


class TestVersionFormat:
    """سرور نسخه را عددی می‌سنجد؛ فرم نقطه‌دار رد می‌شود (تست زنده تأیید کرد)."""

    @pytest.mark.parametrize("raw, expected", [
        ("3.2.7", "327"),
        ("3.2.7\n", "327"),
        ("v3.2.7", "327"),
        ("10.0.1", "1001"),
    ])
    def test_digits_only(self, raw, expected):
        assert digits_only_version(raw) == expected

    def test_credentials_strip_dots_in_payload(self):
        creds = IsacoCredentials(scus="1", username="2", password="3",
                                 client_version="3.2.7")
        assert creds.login_payload()["ClientVersion"] == "327"

    def test_credentials_keep_digit_only_version(self):
        creds = IsacoCredentials(scus="1", username="2", password="3",
                                 client_version="327")
        assert creds.login_payload()["ClientVersion"] == "327"


@pytest.fixture(autouse=True)
def _no_network_version(monkeypatch):
    """جلوی تماس واقعی برای گرفتن version.txt را در تست‌ها می‌گیرد."""
    monkeypatch.setattr(
        "nabz.sources.isaco_web.fetch_client_version", lambda *a, **k: "327"
    )


@pytest.fixture(scope="module")
def keys():
    """دو جفت کلید: یکی نقش سرور، یکی نقش کلاینت."""
    server = RSA.generate(2048)
    client = RSA.generate(2048)
    return {
        "server_pub": server.publickey().export_key().decode(),
        "server_priv": server,
        "client_pub": client.publickey().export_key().decode(),
        "client_priv": client.export_key(pkcs=8).decode(),
        "client_priv_obj": client,
    }


def make_jwt(exp_offset=3600):
    """یک JWT ساختگی با زمان انقضا می‌سازد (امضا واقعی نیست، لازم هم نیست)."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    payload = json.dumps({"username": "9999999999-1234567",
                          "exp": int(time.time()) + exp_offset}).encode()
    payload = base64.urlsafe_b64encode(payload).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.sig"


class FakeIsacoServer:
    """سرور جعلی که مثل ایساکو، درخواست را رمزگشایی و پاسخ را رمز می‌کند."""

    def __init__(self, keys, responses):
        self.keys = keys
        self.responses = responses  # path → dict پاسخ (قبل از رمز)
        self.requests = []          # (path, decrypted_payload)
        self.cookies = FakeCookieJar()
        self.headers = {}

    def get(self, url, **kwargs):
        return FakeHTTPResponse(200, {})

    def post(self, url, json=None, headers=None, timeout=None):
        path = url.split("/api/", 1)[1]
        # درخواست را مثل سرور واقعی رمزگشایی می‌کنیم
        server_priv_pem = self.keys["server_priv"].export_key(pkcs=8).decode()
        payload = decrypt_response(json, server_priv_pem)
        self.requests.append((path, payload, headers or {}))

        raw = self.responses.get(path, {"Success": True, "Data": {}})
        # پاسخ را با کلید عمومی کلاینت رمز می‌کنیم (تا کلاینت با خصوصی باز کند)
        enc = encrypt_request(raw, self.keys["client_pub"])
        return FakeHTTPResponse(200, enc.as_dict())


class FakeCookieJar:
    def keys(self):
        return ["connect.sid"]


class FakeHTTPResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, server):
        self.server = server
        self.headers = {}
        self.cookies = server.cookies

    def get(self, url, **kwargs):
        return self.server.get(url, **kwargs)

    def post(self, url, **kwargs):
        return self.server.post(url, **kwargs)


class TestJwtDecoding:
    def test_reads_expiry(self):
        token = make_jwt(exp_offset=3600)
        exp = _decode_jwt_exp(token)
        assert exp is not None
        assert abs(exp - (time.time() + 3600)) < 5

    def test_returns_none_for_garbage(self):
        assert _decode_jwt_exp("not.a.jwt") is None
        assert _decode_jwt_exp("") is None


class TestLogin:
    def test_successful_login_extracts_token(self, keys):
        token = make_jwt()
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {"Token": token}},
        })
        client = IsacoClient(
            keys["client_priv"], server_public_key=keys["server_pub"],
            session=FakeSession(server),
        )
        creds = IsacoCredentials(scus="1234567", username="9999999999",
                                 password="secret")
        session = client.login(creds)
        assert session.token == token
        assert session.expires_at is not None

    def test_login_exposes_full_name_and_scus(self, keys):
        token = make_jwt()
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {
                "Token": token, "FullName": "کارفرمای نمونه", "Scus": "1234567"}},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        session = client.login(IsacoCredentials(scus="1234567", username="9999999999",
                                                password="x"))
        assert session.full_name == "کارفرمای نمونه"
        assert session.scus == "1234567"

    def test_login_sends_correct_encrypted_payload(self, keys):
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {"Token": make_jwt()}},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        client.login(IsacoCredentials(scus="1234567", username="9999999999",
                                      password="test-pass"))
        path, payload, _ = server.requests[0]
        assert path == "Sec/Login/v2"
        assert payload["Scus"] == "1234567"
        assert payload["UserName"] == "9999999999"
        assert payload["Password"] == "test-pass"

    def test_failed_login_raises(self, keys):
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": False, "Message": "رمز اشتباه"},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        with pytest.raises(IsacoLoginError, match="توکن دریافت نشد"):
            client.login(IsacoCredentials(scus="1", username="2", password="3"))

    def test_double_wrapped_response_is_unwrapped(self, keys):
        """پاسخ دولایه: بعد از رمزگشایی، ``{"data": "<json string>"}`` که باید
        باز هم parse شود. (باگ واقعی که لاگین کارفرما را می‌شکست.)"""
        import json as _json
        token = make_jwt()
        inner = _json.dumps({"Data": {"Token": token, "Scus": "1234567"},
                             "Success": True})
        server = FakeIsacoServer(keys, {
            # سرور یک لایهٔ رشته‌ای اضافه می‌گذارد
            "Sec/Login/v2": {"data": inner},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        session = client.login(IsacoCredentials(scus="1", username="2", password="3"))
        assert session.token == token
        assert session.scus == "1234567"

    def test_authorized_call_includes_token_header(self, keys):
        token = make_jwt()
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {"Token": token}},
            "War/Reports/RepPriceListExcel": {"Success": True, "Data": {"File": "x.xlsx"}},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        client.login(IsacoCredentials(scus="1", username="2", password="3"))
        client.request_price_list()
        _, _, headers = server.requests[1]
        assert headers["Authorization"] == token


class TestTokenExtraction:
    @pytest.mark.parametrize("response, expected", [
        ({"Success": True, "Data": {"Token": "T1"}}, "T1"),
        ({"Success": True, "Data": {"token": "T2"}}, "T2"),
        ({"Token": "T3"}, "T3"),
        ({"Success": False, "Data": {"Token": "T4"}}, None),
        ({"Data": {}}, None),
        ({}, None),
    ])
    def test_extract_token_variants(self, response, expected):
        assert IsacoClient._extract_token(response) == expected


class TestSessionExpiry:
    def test_fresh_session_is_not_expired(self):
        from nabz.sources.isaco_web import IsacoSession
        s = IsacoSession(token="x", expires_at=time.time() + 3600)
        assert not s.is_expired

    def test_old_session_is_expired(self):
        from nabz.sources.isaco_web import IsacoSession
        s = IsacoSession(token="x", expires_at=time.time() - 10)
        assert s.is_expired

    def test_ensure_logged_in_relogins_when_expired(self, keys):
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {"Token": make_jwt()}},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        creds = IsacoCredentials(scus="1", username="2", password="3")
        client.login(creds)
        from nabz.sources.isaco_web import IsacoSession
        client.auth = IsacoSession(token="old", expires_at=time.time() - 1)
        client.ensure_logged_in(creds)
        assert len([r for r in server.requests if r[0] == "Sec/Login/v2"]) == 2


class TestSearchByCode:
    def test_search_sends_eight_digit_code(self, keys):
        token = make_jwt()
        server = FakeIsacoServer(keys, {
            "Sec/Login/v2": {"Success": True, "Data": {"Token": token}},
            "War/Reports/GetPrcLstWgds": {"Success": True, "Data": [
                {"Gds": "0050102697", "Prc": 56000000},
                {"Gds": "0050102699", "Prc": 62720000},
            ]},
        })
        client = IsacoClient(keys["client_priv"],
                             server_public_key=keys["server_pub"],
                             session=FakeSession(server))
        client.login(IsacoCredentials(scus="1", username="2", password="3"))
        result = client.search_by_code("00501026")
        path, payload, _ = server.requests[1]
        assert payload["WgdsGds"] == "00501026"
        assert result["Data"][0]["Gds"] == "0050102697"
