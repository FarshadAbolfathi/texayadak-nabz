"""پل بین تنظیمات ذخیره‌شده و اشیای منطق برنامه.

تب‌های UI به‌جای اینکه هرکدام خودشان قواعد و کلاینت بسازند، از این توابع
استفاده می‌کنند تا رفتار یکسان بماند.
"""

from __future__ import annotations

from decimal import Decimal

from ..config import CredentialStore
from ..db import Database
from ..pricing import PriceBase, PriceRules
from ..stock import StockRules
from ..targets.woocommerce import WooClient, WooConfig


def price_rules_from_db(db: Database) -> PriceRules:
    return PriceRules(
        markup_percent=Decimal(str(db.get_setting("markup_percent", 0))),
        base=PriceBase(db.get_setting("price_base", "vat")),
        round_to=int(db.get_setting("round_to", 1000)),
        max_change_percent=Decimal(str(db.get_setting("max_change_percent", 50))),
    )


def stock_rules_from_db(db: Database) -> StockRules:
    return StockRules(
        max_on_site=int(db.get_setting("max_on_site", 2)),
        reserve=int(db.get_setting("reserve", 0)),
    )


def woo_client_from_store(store: CredentialStore) -> WooClient | None:
    """کلاینت ووکامرس را از اعتبارنامه‌های ذخیره‌شده می‌سازد.

    اگر اعتبارنامه‌ها کامل نباشند، ``None`` برمی‌گرداند تا UI پیام مناسب بدهد.
    """
    creds = store.load_woo()
    if not (creds.base_url and creds.consumer_key and creds.consumer_secret):
        return None
    return WooClient(WooConfig(
        base_url=creds.base_url,
        consumer_key=creds.consumer_key,
        consumer_secret=creds.consumer_secret,
        wp_user=creds.wp_user,
        wp_app_password=creds.wp_app_password,
    ))


def categorizer_from_db(db: Database, categories):
    """پیشنهاددهندهٔ دسته را با قواعد و تنظیمات ذخیره‌شده می‌سازد."""
    from ..categorize import Categorizer, rules_from_settings

    return Categorizer(
        categories,
        rules_from_settings(db.get_setting("category_rules", [])),
        include_parents=bool(db.get_setting("category_include_parents", True)),
        default_category=int(db.get_setting("category_default", 0) or 0) or None,
        auto_match=bool(db.get_setting("category_auto_match", True)),
    )
