"""تست رمزنگاری ایساکو.

از یک جفت کلید RSA آزمایشی (نه کلید واقعی ایساکو) استفاده می‌کنیم تا
دور کامل رمز→رمزگشایی را بسنجیم. یک تست هم فرمت خروجی را با آنچه در
درخواست واقعی دیدیم مقایسه می‌کند.
"""

import base64
import json

import pytest
from Crypto.PublicKey import RSA

from nabz.sources.isaco_crypto import (
    EncryptedBody,
    IsacoCryptoError,
    _evp_bytes_to_key,
    decrypt_response,
    encrypt_request,
)


@pytest.fixture(scope="module")
def keypair():
    """یک جفت کلید آزمایشی؛ نقش «کلید سرور» و «کلید کلاینت» را بازی می‌کند."""
    key = RSA.generate(2048)
    public = key.publickey().export_key().decode()
    private = key.export_key(pkcs=8).decode()
    return public, private


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self, keypair):
        public, private = keypair
        payload = {"WgdsGds": "00501026", "name": "سنسور اکسیژن"}
        body = encrypt_request(payload, server_public_key=public)
        assert decrypt_response(body, private) == payload

    def test_works_with_list_payload(self, keypair):
        public, private = keypair
        payload = [{"a": 1}, {"b": "دو"}]
        body = encrypt_request(payload, server_public_key=public)
        assert decrypt_response(body, private) == payload

    def test_persian_survives_round_trip(self, keypair):
        public, private = keypair
        payload = {"شرح": "کاسه نمد چپ هوزينگ ديفرانسيل ۴۰۵"}
        body = encrypt_request(payload, server_public_key=public)
        assert decrypt_response(body, private) == payload

    def test_two_encryptions_differ(self, keypair):
        """هر بار salt و عبارت‌عبور تصادفی است ⇒ خروجی نباید یکی باشد."""
        public, _ = keypair
        a = encrypt_request({"x": 1}, server_public_key=public)
        b = encrypt_request({"x": 1}, server_public_key=public)
        assert a.data != b.data
        assert a.key != b.key


class TestWireFormat:
    def test_data_uses_openssl_salted_header(self, keypair):
        public, _ = keypair
        body = encrypt_request({"x": 1}, server_public_key=public)
        assert base64.b64decode(body.data)[:8] == b"Salted__"

    def test_ciphertext_is_block_aligned(self, keypair):
        public, _ = keypair
        body = encrypt_request({"x": 1}, server_public_key=public)
        ciphertext = base64.b64decode(body.data)[16:]
        assert len(ciphertext) % 16 == 0

    def test_encrypted_key_is_256_bytes_for_rsa2048(self, keypair):
        public, _ = keypair
        body = encrypt_request({"x": 1}, server_public_key=public)
        assert len(base64.b64decode(body.key)) == 256

    def test_body_matches_captured_request_shape(self, keypair):
        """درخواست واقعی ایساکو دقیقاً همین دو کلید را داشت."""
        public, _ = keypair
        body = encrypt_request({"x": 1}, server_public_key=public)
        assert set(body.as_dict()) == {"data", "key"}


class TestEvpBytesToKey:
    def test_matches_known_openssl_vector(self):
        """بردار مرجع OpenSSL: pass='password' salt=0x0102030405060708.

        با ``openssl enc -aes-256-cbc -P -S 0102030405060708
        -pass pass:password -md md5`` تأیید شد.
        """
        key, iv = _evp_bytes_to_key(b"password", bytes.fromhex("0102030405060708"))
        assert key.hex() == (
            "e7b0971e52ca5cc8d0539fb3412f6316"
            "f7ba2e6ee293d9f3457b99436b51ce02"
        )
        assert iv.hex() == "8d450e2ed75a84a923d4eac9fe49226b"


class TestErrors:
    def test_wrong_private_key_raises_clear_error(self, keypair):
        public, _ = keypair
        other = RSA.generate(2048).export_key(pkcs=8).decode()
        body = encrypt_request({"x": 1}, server_public_key=public)
        with pytest.raises(IsacoCryptoError, match="کلید"):
            decrypt_response(body, other)

    def test_malformed_data_raises(self, keypair):
        _, private = keypair
        bad = EncryptedBody(data=base64.b64encode(b"not salted..").decode(), key="")
        with pytest.raises(IsacoCryptoError):
            decrypt_response(bad, private)

    def test_invalid_public_key_raises(self):
        with pytest.raises(IsacoCryptoError, match="کلید عمومی"):
            encrypt_request({"x": 1}, server_public_key="نامعتبر")
