"""تست نگهداری اعتبارنامه‌ها با backend حافظه‌ای."""

from nabz.config import (
    CredentialStore,
    IsacoCredentialsConfig,
    MemoryBackend,
    WooCredentials,
)


def store():
    return CredentialStore(backend=MemoryBackend())


class TestWoo:
    def test_save_and_load(self):
        s = store()
        s.save_woo(WooCredentials(
            base_url="https://texayadak.com",
            consumer_key="ck_x", consumer_secret="cs_y"))
        loaded = s.load_woo()
        assert loaded.base_url == "https://texayadak.com"
        assert loaded.consumer_key == "ck_x"
        assert loaded.consumer_secret == "cs_y"

    def test_empty_when_unset(self):
        assert store().load_woo() == WooCredentials()


class TestIsaco:
    def test_save_and_load(self):
        s = store()
        s.save_isaco(IsacoCredentialsConfig(
            scus="1234567", username="9999999999", password="test-pass"))
        loaded = s.load_isaco()
        assert loaded.scus == "1234567"
        assert loaded.username == "9999999999"
        assert loaded.password == "test-pass"

    def test_empty_when_unset(self):
        assert store().load_isaco() == IsacoCredentialsConfig()


class TestClear:
    def test_clear_removes_all(self):
        s = store()
        s.save_woo(WooCredentials(base_url="x"))
        s.save_isaco(IsacoCredentialsConfig(scus="1"))
        s.clear()
        assert s.load_woo() == WooCredentials()
        assert s.load_isaco() == IsacoCredentialsConfig()


class TestBackend:
    def test_memory_backend_not_secure(self):
        assert not store().is_secure

    def test_backend_isolation(self):
        b = MemoryBackend()
        s1 = CredentialStore(backend=b)
        s2 = CredentialStore(backend=b)
        s1.save_woo(WooCredentials(base_url="shared"))
        # همان backend ⇒ داده مشترک
        assert s2.load_woo().base_url == "shared"
