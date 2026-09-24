"""رمزنگاری درخواست/پاسخ پورتال B2B ایساکو.

پورتال ایساکو بدنهٔ درخواست‌ها و پاسخ‌ها را رمز می‌کند. طرح آن یک
رمزنگاری ترکیبی (hybrid) است که از روی باندل جاوااسکریپت خودِ سایت
مهندسی معکوس شده و با یک درخواست واقعی تأیید شده است:

    درخواست (کلاینت → سرور)
        ۱) یک عبارت‌عبور تصادفی ساخته می‌شود:
           CryptoJS.lib.WordArray.random(32).toString()  →  ۶۴ کاراکتر hex
        ۲) بدنه با AES رمز می‌شود، دقیقاً مثل ``CryptoJS.AES.encrypt(json, pass)``
           که خروجی‌اش فرمت OpenSSL است: ``Salted__`` + salt(۸ بایت) + ciphertext،
           و کلید/iv با EVP_BytesToKey (MD5) از عبارت‌عبور و salt ساخته می‌شود.
        ۳) عبارت‌عبور با RSA-OAEP-SHA256 و «کلید عمومی سرور» رمز می‌شود.
        ۴) بدنهٔ نهایی: ``{"data": <b64 AES>, "key": <b64 RSA>}``

    پاسخ (سرور → کلاینت)
        همان ساختار ``{data, key}`` برمی‌گردد، ولی این بار عبارت‌عبور با
        «کلید عمومی کلاینت» رمز شده و با «کلید خصوصی کلاینت» (که داخل باندل
        سایت است) رمزگشایی می‌شود.

نکتهٔ امنیتی مهم: کلید خصوصی کلاینت داخل جاوااسکریپت عمومی سایت قرار دارد،
پس این رمزنگاری «محرمانگی سمت پاسخ» ایجاد نمی‌کند و صرفاً یک لایهٔ مبهم‌سازی
است. ما فقط همان کاری را می‌کنیم که مرورگر می‌کند؛ چیزی را نمی‌شکنیم.
این کلیدها عمومی‌اند و ممکن است ایساکو روزی عوضشان کند، پس در
:mod:`nabz.sources.isaco_web` قابل تنظیم‌اند.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

#: کلید عمومی سرور ایساکو (از باندل سایت، برای رمز کردن درخواست).
ISACO_SERVER_PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxo9gBgRy4bpZcl+d74hr"
    "U8LH9EiIEbOCnrCSWyqFUYMYLbROeEiigX1vGb/ntdIDda3+pWN0JlbwQ/bKxWtp"
    "JiDFGC6i3PmyV+5mBPA+EVMVxIyW0frZqlrVVTnCmnZKLbgp/UM9wf167GopGaZh"
    "gqdkITa0+KxSzWRGg5KXzNHu80HWICSsVkMiC5weVte8t30o32qYhqc3Csk5Yiz1"
    "osAaQiwSD/SgEnMqlH5TCAvYdJ98aKQkfIeyOUwaFegDM5MkSv27Gnq7/dkMXW/p"
    "PmL7k59UiFphuFWQ/dEMAmf4y7wlboW6JVr9eTX7Dj4rofgS95Xi1A9wTKpRySTb"
    "DQIDAQAB"
)

#: طول عبارت‌عبور AES بر حسب بایتِ WordArray؛ ``.toString()`` آن را
#: به این تعداد × ۲ کاراکتر hex تبدیل می‌کند.
_PASSPHRASE_WORDS = 32


class IsacoCryptoError(RuntimeError):
    """رمزنگاری یا رمزگشایی بدنهٔ ایساکو شکست خورد."""


@dataclass(frozen=True, slots=True)
class EncryptedBody:
    """بدنهٔ ``{data, key}`` که به سرور فرستاده یا از آن دریافت می‌شود."""

    data: str
    key: str

    def as_dict(self) -> dict[str, str]:
        return {"data": self.data, "key": self.key}


def _evp_bytes_to_key(
    passphrase: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16
) -> tuple[bytes, bytes]:
    """همان الگوریتم OpenSSL/CryptoJS برای ساخت کلید و iv از عبارت‌عبور.

    از MD5 استفاده می‌کند چون CryptoJS این کار را می‌کند؛ انتخاب ما نیست،
    باید عیناً با سایت یکی باشد وگرنه سرور نمی‌تواند رمزگشایی کند.
    """
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + passphrase + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def _load_public_key(pem_or_b64: str) -> RSA.RsaKey:
    body = pem_or_b64.strip()
    if "BEGIN" not in body:
        body = f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"
    try:
        return RSA.import_key(body)
    except (ValueError, IndexError, TypeError) as exc:
        raise IsacoCryptoError("کلید عمومی ایساکو نامعتبر است") from exc


def _load_private_key(pem_or_b64: str) -> RSA.RsaKey:
    body = pem_or_b64.strip()
    if "BEGIN" not in body:
        body = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"
    try:
        return RSA.import_key(body)
    except (ValueError, IndexError, TypeError) as exc:
        raise IsacoCryptoError("کلید خصوصی ایساکو نامعتبر است") from exc


def encrypt_request(
    payload: dict | list,
    server_public_key: str = ISACO_SERVER_PUBLIC_KEY,
) -> EncryptedBody:
    """بدنهٔ درخواست را دقیقاً مثل مرورگر ایساکو رمز می‌کند."""
    passphrase = get_random_bytes(_PASSPHRASE_WORDS).hex().encode("ascii")
    salt = get_random_bytes(8)
    key, iv = _evp_bytes_to_key(passphrase, salt)

    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    pad = 16 - (len(plaintext) % 16)
    plaintext += bytes([pad]) * pad
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext)
    blob = b"Salted__" + salt + ciphertext

    rsa = PKCS1_OAEP.new(_load_public_key(server_public_key), hashAlgo=SHA256)
    encrypted_key = rsa.encrypt(passphrase)

    return EncryptedBody(
        data=base64.b64encode(blob).decode("ascii"),
        key=base64.b64encode(encrypted_key).decode("ascii"),
    )


def decrypt_response(
    body: EncryptedBody | dict[str, str],
    client_private_key: str,
) -> dict | list:
    """پاسخ رمزشدهٔ سرور را با کلید خصوصی کلاینت باز می‌کند."""
    if isinstance(body, dict):
        body = EncryptedBody(data=body["data"], key=body["key"])

    rsa = PKCS1_OAEP.new(_load_private_key(client_private_key), hashAlgo=SHA256)
    try:
        passphrase = rsa.decrypt(base64.b64decode(body.key))
    except ValueError as exc:
        raise IsacoCryptoError(
            "رمزگشایی کلید پاسخ شکست خورد؛ احتمالاً کلید ایساکو عوض شده"
        ) from exc

    blob = base64.b64decode(body.data)
    if blob[:8] != b"Salted__":
        raise IsacoCryptoError("پاسخ ایساکو فرمت مورد انتظار (Salted__) را ندارد")

    salt = blob[8:16]
    ciphertext = blob[16:]
    key, iv = _evp_bytes_to_key(passphrase, salt)
    plaintext = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)
    plaintext = plaintext[: -plaintext[-1]]  # حذف PKCS7 padding

    try:
        return json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise IsacoCryptoError("پاسخ رمزگشایی‌شده JSON معتبر نیست") from exc
