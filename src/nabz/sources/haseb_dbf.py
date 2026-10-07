"""خواندن دیتابیس نرم‌افزار حسابداری حاسب (فرمت dBase III).

حاسب نسخهٔ DX 8 داده‌هایش را در فایل‌های ``.DBF`` نگه می‌دارد، با
انکودینگ **CP1256** و ایندکس‌های ``.MDX``. ما فقط می‌خوانیم و **هرگز
نمی‌نویسیم**؛ فایل هم پیش از خواندن در یک مسیر موقت کپی می‌شود تا
اگر حاسب همان لحظه در حال نوشتن بود، نه ما رکورد نصفه بخوانیم و نه
مزاحم کار کارفرما شویم.

جدول کالا ``DBF2/cal.DBF`` است و ستون‌های مهمش:

    COD       کد کالا (همان کد تدارکاتی ایساکو، بدون صفر ابتدایی)
    NAME      نام کالا
    MOJ       موجودی
    COD_ANB   کد انبار / تأمین‌کننده
    NAME_ANB  نام انبار
    GH_FO     قیمت فروش (در این نصب همیشه صفر است)
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

#: انکودینگ فارسی فایل‌های حاسب. با نمونهٔ واقعی تأیید شد.
ENCODING = "cp1256"

#: بایت اول هر رکورد؛ ``*`` یعنی رکورد حذف‌شده.
_DELETED = 0x2A
#: پایان لیست توصیف فیلدها در هدر.
_HEADER_TERMINATOR = 0x0D


class DbfError(RuntimeError):
    """فایل DBF قابل خواندن نیست."""


@dataclass(frozen=True, slots=True)
class DbfField:
    """توصیف یک ستون در هدر DBF."""

    name: str
    type: str   # C متن، N عدد، L منطقی، D تاریخ، M یادداشت
    length: int
    decimals: int
    offset: int  # جای شروع این فیلد در بایت‌های رکورد


class DbfReader:
    """خوانندهٔ فقط-خواندنی فایل‌های dBase III.

    عمداً به کتابخانهٔ بیرونی وابسته نیست: فرمت DBF ساده و پایدار است و
    یک وابستگی کمتر یعنی یک چیز کمتر برای شکستن هنگام بسته‌بندی exe.

    >>> with DbfReader("cal.DBF") as db:      # doctest: +SKIP
    ...     print(db.record_count)
    ...     for row in db.rows(fields=["COD", "MOJ"]):
    ...         print(row["COD"], row["MOJ"])
    """

    def __init__(
        self,
        path: str | Path,
        *,
        encoding: str = ENCODING,
        use_copy: bool = True,
    ) -> None:
        self.source_path = Path(path)
        self.encoding = encoding
        self._use_copy = use_copy
        self._temp: Path | None = None
        self._handle = None
        self.fields: list[DbfField] = []
        self.record_count = 0
        self.header_length = 0
        self.record_length = 0

    # -- چرخهٔ عمر ------------------------------------------------------

    def __enter__(self) -> "DbfReader":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        if not self.source_path.is_file():
            raise DbfError(f"فایل پیدا نشد: {self.source_path}")

        read_path = self.source_path
        if self._use_copy:
            # کپی در مسیر موقت: هم از رکورد نصفه جلوگیری می‌کند،
            # هم مطمئن می‌شویم هیچ‌وقت فایل اصلی را قفل نمی‌کنیم.
            fd, tmp = tempfile.mkstemp(prefix="nabz_", suffix=".dbf")
            import os

            os.close(fd)
            self._temp = Path(tmp)
            shutil.copy2(self.source_path, self._temp)
            read_path = self._temp

        self._handle = read_path.open("rb")
        self._read_header()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._temp is not None:
            self._temp.unlink(missing_ok=True)
            self._temp = None

    # -- هدر ------------------------------------------------------------

    def _read_header(self) -> None:
        assert self._handle is not None
        head = self._handle.read(32)
        if len(head) < 32:
            raise DbfError(f"هدر فایل ناقص است: {self.source_path}")

        (self.record_count, self.header_length, self.record_length) = struct.unpack(
            "<IHH", head[4:12]
        )
        if self.record_length == 0:
            raise DbfError(f"طول رکورد صفر است: {self.source_path}")

        offset = 1  # بایت اول رکورد پرچم حذف است
        self.fields = []
        while True:
            raw = self._handle.read(32)
            if len(raw) < 32 or raw[0] in (_HEADER_TERMINATOR, 0x00):
                break
            name = raw[:11].split(b"\x00")[0].decode("ascii", "replace").strip()
            self.fields.append(
                DbfField(
                    name=name,
                    type=chr(raw[11]),
                    length=raw[16],
                    decimals=raw[17],
                    offset=offset,
                )
            )
            offset += raw[16]

        if not self.fields:
            raise DbfError(f"هیچ فیلدی در هدر پیدا نشد: {self.source_path}")

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    # -- رکوردها --------------------------------------------------------

    def rows(
        self,
        *,
        fields: list[str] | None = None,
        include_deleted: bool = False,
    ) -> Iterator[dict[str, str]]:
        """رکوردها را یکی‌یکی برمی‌گرداند.

        :param fields: فقط این ستون‌ها خوانده شوند. خواندن ۴ ستون از یک
            جدول ۹۳ ستونی چند برابر سریع‌تر است و داده‌ای که لازم نداریم
            اصلاً وارد حافظه نمی‌شود.
        :param include_deleted: رکوردهای حذف‌شده هم برگردانده شوند.
        """
        if self._handle is None:
            raise DbfError("فایل باز نیست؛ از context manager استفاده کنید.")

        wanted = self.fields
        if fields is not None:
            requested = {n.upper() for n in fields}
            wanted = [f for f in self.fields if f.name.upper() in requested]
            unknown = requested - {f.name.upper() for f in self.fields}
            if unknown:
                raise DbfError(
                    f"این ستون‌ها در {self.source_path.name} وجود ندارند: "
                    f"{', '.join(sorted(unknown))}"
                )

        handle = self._handle
        handle.seek(self.header_length)
        for _ in range(self.record_count):
            buffer = handle.read(self.record_length)
            if len(buffer) < self.record_length:
                break  # فایل کوتاه‌تر از چیزی است که هدر ادعا می‌کند
            deleted = buffer[0] == _DELETED
            if deleted and not include_deleted:
                continue
            row = {
                f.name: buffer[f.offset : f.offset + f.length]
                .decode(self.encoding, "replace")
                .strip()
                for f in wanted
            }
            if include_deleted:
                row["_deleted"] = "1" if deleted else "0"
            yield row


# -- جدول کالا ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HasebItem:
    """یک کالا در جدول ``cal.DBF``."""

    code: str            # کد نرمال‌شدهٔ ۱۰ رقمی
    raw_code: str        # همان چیزی که در حاسب بود
    name: str
    quantity: Decimal    # موجودی
    warehouse_id: int
    warehouse_name: str
    #: قیمت فروش ثبت‌شده در حاسب (ریال)؛ در خیلی از نصب‌ها صفر است.
    sale_price: Decimal = Decimal(0)


def _to_decimal(value: str) -> Decimal:
    try:
        return Decimal(value.strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)


def load_products(
    cal_path: str | Path,
    *,
    warehouses: set[int] | None = None,
) -> dict[str, HasebItem]:
    """جدول کالای حاسب را می‌خواند.

    :param warehouses: اگر داده شود، فقط کالاهای این انبارها خوانده
        می‌شوند. برای فاز اول که فقط کالاهای ایساکویی مدنظر است،
        شناسهٔ انبارهای ایساکو را اینجا می‌دهیم.

    اگر یک کد در چند انبار تکرار شده باشد، موجودی‌ها **جمع** می‌شوند؛
    چون از دید سایت فقط یک محصول با یک SKU وجود دارد.
    """
    from ..skucode import normalize

    result: dict[str, HasebItem] = {}
    columns = ["COD", "NAME", "MOJ", "COD_ANB", "NAME_ANB"]

    with DbfReader(cal_path) as reader:
        has_price = "GH_FO" in {n.upper() for n in reader.field_names()}
        if has_price:
            columns = [*columns, "GH_FO"]
        for row in reader.rows(fields=columns):
            raw = row["COD"].strip()
            code = normalize(raw)
            if not code:
                continue

            try:
                warehouse_id = int(row["COD_ANB"] or 0)
            except ValueError:
                warehouse_id = 0
            if warehouses is not None and warehouse_id not in warehouses:
                continue

            quantity = _to_decimal(row["MOJ"])
            sale_price = _to_decimal(row.get("GH_FO", "")) if has_price else Decimal(0)
            existing = result.get(code)
            if existing is not None:
                quantity += existing.quantity
                sale_price = max(sale_price, existing.sale_price)

            result[code] = HasebItem(
                code=code,
                raw_code=raw,
                name=row["NAME"].strip(),
                quantity=quantity,
                warehouse_id=warehouse_id,
                warehouse_name=row["NAME_ANB"].strip(),
                sale_price=sale_price,
            )

    return result


def load_warehouses(anb_path: str | Path) -> dict[int, str]:
    """جدول انبارها (``anb.DBF``) را می‌خواند: شناسه → نام."""
    result: dict[int, str] = {}
    with DbfReader(anb_path) as reader:
        for row in reader.rows(fields=["COD", "NAME"]):
            try:
                result[int(row["COD"] or 0)] = row["NAME"].strip()
            except ValueError:
                continue
    return result


@dataclass(slots=True)
class WarehouseInfo:
    """یک انبار حاسب با آمار کالاهایش (برای انتخاب انبار در برنامه)."""

    id: int
    name: str
    items: int = 0          # تعداد ردیف کالا
    in_stock: int = 0       # ردیف‌های با موجودی بیشتر از صفر


def list_warehouses(cal_path: str | Path) -> list[WarehouseInfo]:
    """انبارهایی که در جدول کالا (``cal.DBF``) آمده‌اند، با تعداد کالا.

    مستقیم از ستون‌های ``COD_ANB``/``NAME_ANB`` همان جدول کالا خوانده
    می‌شود (فقط خواندنی) تا به فایل جدای انبارها نیازی نباشد.
    """
    found: dict[int, WarehouseInfo] = {}
    with DbfReader(cal_path) as reader:
        for row in reader.rows(fields=["COD_ANB", "NAME_ANB", "MOJ"]):
            try:
                wid = int(row["COD_ANB"] or 0)
            except ValueError:
                continue
            info = found.get(wid)
            if info is None:
                info = found[wid] = WarehouseInfo(wid, row["NAME_ANB"].strip())
            elif not info.name:
                info.name = row["NAME_ANB"].strip()
            info.items += 1
            if _to_decimal(row["MOJ"]) > 0:
                info.in_stock += 1
    return sorted(found.values(), key=lambda w: w.id)
