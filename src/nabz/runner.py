"""اجرای برنامهٔ سینک روی ووکامرس، با snapshot برای رول‌بک.

این لایه، :class:`~nabz.engine.SyncPlan` را می‌گیرد و روی سایت اعمال می‌کند،
ولی **پیش از هر تغییر، مقدار قبلی را در دیتابیس ثبت می‌کند** تا اگر لازم شد
بتوان کل اجرا را برگرداند. همچنین اجرا را در جدول ``runs`` ثبت می‌کند.

جداسازی مهم: موتور (:mod:`nabz.engine`) تصمیم می‌گیرد چه تغییری لازم است،
این ماژول آن را با ایمنی اعمال می‌کند، و ووکامرس (:mod:`nabz.targets`)
فقط ارتباط شبکه است. هر سه جدا تست می‌شوند.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database, Snapshot
from .engine import SyncPlan
from .targets.woocommerce import BatchOutcome, WooClient


@dataclass(slots=True)
class ApplyResult:
    run_id: int
    outcome: BatchOutcome
    applied_count: int
    summary: dict


def _plan_to_snapshots(plan: SyncPlan, applied_ids: set[int]) -> list[Snapshot]:
    """از برنامهٔ سینک، snapshot قیمت/موجودی قبل و بعد را می‌سازد."""
    snaps: list[Snapshot] = []
    for item in plan.items:
        if not item.changes or item.needs_review:
            continue
        snaps.append(
            Snapshot(
                product_id=item.product_id,
                sku=item.sku,
                old_price=str(item.current_price) if item.current_price is not None else None,
                new_price=str(item.new_price) if item.new_price is not None else None,
                old_stock=item.current_stock,
                new_stock=item.new_stock,
                old_status=(
                    item.stock_result.status.value
                    if item.stock_result and item.current_stock == 0
                    else ("instock" if item.current_stock else None)
                ),
                new_status=item.stock_result.status.value if item.stock_result else None,
                applied=item.product_id in applied_ids,
            )
        )
    return snaps


def apply_plan(
    plan: SyncPlan,
    woo: WooClient,
    db: Database,
    *,
    mode: str = "manual",
    include_price: bool = True,
    include_stock: bool = True,
    note: str | None = None,
) -> ApplyResult:
    """برنامه را اعمال می‌کند و همه‌چیز را برای رول‌بک ثبت می‌کند.

    ترتیب کار به‌گونه‌ای است که حتی اگر ارسال به ووکامرس وسط کار خطا دهد،
    snapshotها ثبت شده‌اند و آنچه اعمال شده قابل بازگشت است.
    """
    updates = plan.to_woo_updates(
        include_price=include_price, include_stock=include_stock
    )
    run_id = db.start_run(mode, note=note)

    if not updates:
        db.finish_run(run_id, "done", plan.summary())
        return ApplyResult(run_id, BatchOutcome(), 0, plan.summary())

    try:
        outcome = woo.batch_update(updates)
    except Exception as exc:
        db.log("error", f"خطا در ارسال به ووکامرس: {exc}", run_id=run_id)
        db.finish_run(run_id, "failed", plan.summary())
        raise

    applied_ids = set(outcome.updated)
    snaps = _plan_to_snapshots(plan, applied_ids)
    db.record_snapshots(run_id, snaps)

    summary = plan.summary()
    summary["applied"] = len(applied_ids)
    summary["failed"] = len(outcome.failed)
    db.finish_run(run_id, "done" if outcome.ok else "done", summary)
    db.log(
        "info",
        f"سینک {mode}: {len(applied_ids)} محصول به‌روز شد، "
        f"{len(outcome.failed)} خطا.",
        run_id=run_id,
    )

    return ApplyResult(run_id, outcome, len(applied_ids), summary)


def rollback_run(run_id: int, woo: WooClient, db: Database) -> BatchOutcome:
    """یک اجرا را به مقادیر قبلی برمی‌گرداند.

    از snapshotهای ذخیره‌شده استفاده می‌کند و مقدار قبلی هر محصول را
    دوباره روی سایت می‌نشاند.
    """
    snaps = db.rollback_data(run_id)
    if not snaps:
        return BatchOutcome()

    reverts = [snap.to_woo_revert() for snap in snaps]
    outcome = woo.batch_update(reverts)
    db.mark_reverted(run_id)
    db.log(
        "info",
        f"بازگردانی اجرای #{run_id}: {len(outcome.updated)} محصول به مقدار قبلی برگشت.",
        run_id=run_id,
    )
    return outcome
