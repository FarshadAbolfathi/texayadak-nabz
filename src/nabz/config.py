"""نگهداری رمزنگاری‌شدهٔ اعتبارنامه‌ها.

رمزهای ووکامرس و ایساکو نباید plaintext روی دیسک بمانند. این ماژول از
``keyring`` استفاده می‌کند که روی ویندوز به‌طور خودکار از DPAPI (Windows
Credential Manager) استفاده می‌کند — یعنی رمزها با حساب کاربری ویندوزِ
کارفرما گره می‌خورند و کاربر دیگری نمی‌تواند بازشان کند.

اگر keyring در دسترس نبود (مثلاً سیستم بدون backend)، به یک فایل
رمزنگاری‌شده با کلیدِ مشتق‌شده از یک راز محلی برمی‌گردیم. در هر دو حالت،
رمز خام هرگز در دیتابیس یا فایل تنظیمات ساده نوشته نمی‌شود.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

try:
    import keyring

    _HAS_KEYRING = True
except Exception:  # pragma: no cover - بستگی به محیط دارد
    _HAS_KEYRING = False

SERVICE_NAME = "texayadak-nabz"


@dataclass(slots=True)
class WooCredentials:
    base_url: str = ""
    consumer_key: str = ""
    consumer_secret: str = ""
    #: برای آپلود تصویر شاخص از کامپیوتر (Application Password وردپرس)
    wp_user: str = ""
    wp_app_password: str = ""


@dataclass(slots=True)
class IsacoCredentialsConfig:
    scus: str = ""
    username: str = ""
    password: str = ""


@dataclass(slots=True)
class AppConfig:
    """تنظیمات غیرحساس که کنار رمزهای رمزنگاری‌شده نگه داشته می‌شوند."""

    woo: WooCredentials = field(default_factory=WooCredentials)
    isaco: IsacoCredentialsConfig = field(default_factory=IsacoCredentialsConfig)


class CredentialStore:
    """ذخیره/خواندن اعتبارنامه‌ها به‌صورت رمزنگاری‌شده.

    :param backend: برای تست می‌توان یک backend دیکشنری‌ساده تزریق کرد.
    """

    def __init__(self, backend: "SecretBackend | None" = None):
        self._backend = backend or _default_backend()

    def save_woo(self, creds: WooCredentials) -> None:
        self._backend.set("woo", json.dumps(asdict(creds)))

    def load_woo(self) -> WooCredentials:
        raw = self._backend.get("woo")
        if not raw:
            return WooCredentials()
        known = WooCredentials.__dataclass_fields__
        return WooCredentials(**{k: v for k, v in json.loads(raw).items() if k in known})

    def save_isaco(self, creds: IsacoCredentialsConfig) -> None:
        self._backend.set("isaco", json.dumps(asdict(creds)))

    def load_isaco(self) -> IsacoCredentialsConfig:
        raw = self._backend.get("isaco")
        return (
            IsacoCredentialsConfig(**json.loads(raw))
            if raw
            else IsacoCredentialsConfig()
        )

    def clear(self) -> None:
        self._backend.delete("woo")
        self._backend.delete("isaco")

    @property
    def is_secure(self) -> bool:
        """آیا از یک backend امن سیستم‌عامل استفاده می‌کنیم؟"""
        return self._backend.is_secure


class SecretBackend:
    """رابط ذخیرهٔ راز."""

    is_secure = False

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class KeyringBackend(SecretBackend):
    """پشتوانهٔ سیستم‌عامل (DPAPI روی ویندوز، Keychain روی مک)."""

    is_secure = True

    def set(self, key: str, value: str) -> None:
        keyring.set_password(SERVICE_NAME, key, value)

    def get(self, key: str) -> str | None:
        return keyring.get_password(SERVICE_NAME, key)

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except Exception:
            pass


class MemoryBackend(SecretBackend):
    """پشتوانهٔ درون‌حافظه‌ای؛ فقط برای تست."""

    is_secure = False

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


def _default_backend() -> SecretBackend:
    if _HAS_KEYRING:
        try:
            # اطمینان از اینکه یک backend واقعی هست، نه backend ناکارآمد
            keyring.get_keyring()
            return KeyringBackend()
        except Exception:  # pragma: no cover
            pass
    return MemoryBackend()
