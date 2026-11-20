"""Bazadan yoqilg'i ma'lumotlarini o'qish — FAQAT SELECT, parametrli.

Olti jadval o'qiladi:
    waybill            bakdagi qoldiq, spidometr, quyilgan litr
    fuel_record        sarf yozuvlari, motor-soat, kutilgan sarf
    fuel_norm          norma (100 km ga yoki motor-soatga) va toleransi
    fuel_limit         haydovchi/mashinaga kunlik yoki oylik chegara
    transport_vehicle  mashina raqami va markasi
    driver             haydovchi ismi va tabel raqami

BAZAGA ZARAR YETMASLIGI uch qatlam bilan kafolatlangan:
  1. bu faylda bitta ham yozuv amali yo'q — faqat `select`;
  2. ulanish `default_transaction_read_only=on` bilan ochiladi
     (`atil_chatbot/db/connect_db_for_server.py`), ya'ni PostgreSQL yozishni
     tranzaksiya darajasida rad etadi;
  3. `.env` dagi `ATIL_DB_USER` da faqat SELECT huquqi bor.

NIMA UCHUN `run_query` EMAS: chatbotdagi `run_query(sql: str)` faqat matn
qabul qiladi, chunki uni LLM yozadi va `sql_guard` dan o'tkazish shart. Bu
yerda SQL ni model emas, shu fayl yozadi, ammo sanalar FOYDALANUVCHIDAN
keladi. Ularni matnga yopishtirish SQL-in'ektsiya yo'li bo'lardi, shuning
uchun psycopg2 parametrlari (`%s`) ishlatiladi.
"""

from __future__ import annotations

import logging
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

# `db.connect_db_for_server` paket ichida yassi nom bilan import qiladi
# (`from config import ...`), shuning uchun `atil_chatbot` sys.path da
# bo'lishi shart. main.py buni allaqachon qiladi; bu yerdagi takror shu
# modulni alohida ham (`python -m oil_detection.detector`) ishlata olish uchun.
_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)

#: Sarf hisoblanadigan yo'l varaqasi holatlari — hujjat yopilgan yoki
#: qaytarilgan bo'lishi kerak. IN_USE/ISSUED da qaytish ko'rsatkichlari hali
#: yo'q, CANCELLED esa umuman bajarilmagan reys.
CLOSED_STATUSES = ("CLOSED", "RETURNED")

#: Modul o'qiydigan jadvallar — `data_quality.row_counts` da shular chiqadi.
SOURCE_TABLES = (
    "waybill",
    "fuel_record",
    "fuel_norm",
    "fuel_limit",
    "transport_vehicle",
    "driver",
)


class OilDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, tuple(params or ()))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Yoqilg'i so'rovi bajarilmadi: %s", message[:300])
        raise OilDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise OilDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


def to_float(value: Any) -> float | None:
    """`numeric` ustunlar psycopg2 dan `Decimal` bo'lib keladi — JSON uchun float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ Reyestrlar


def row_counts(tables: Sequence[str] = SOURCE_TABLES) -> dict[str, int]:
    """Jadvallardagi yozuvlar soni — javobdagi `data_quality` uchun.

    NIMA UCHUN `count(*)`, `pg_stat_user_tables` EMAS. Ilgari bu yerda
    `n_live_tup` o'qilardi — u yengil, lekin bu bazada YOLG'ON: statistika
    hech qachon yig'ilmagan (`last_analyze` ham, `last_autoanalyze` ham
    NULL), shuning uchun 128 qatorli `transport_vehicle` javobda "0"
    bo'lib ko'rinardi. Undan chiqarilgan "Bo'sh jadvallar: ..." izohi ham
    yolg'on bo'lardi — o'sha javobning o'zida o'sha jadvaldan o'qilgan
    mashinalar turgan holda.

    Bo'sh jadval natijani jimgina o'zgartirib yuboradi, shuning uchun bu
    maydon javobda ko'rinishi shart — va TO'G'RI ko'rinishi shart.

    Aniq son bu yerda qimmat emas: jadvallar kichik va hammasi BITTA
    so'rovda, bitta borib-kelishda sanaladi.
    """
    # Jadval nomlari `SOURCE_TABLES` dan keladi (foydalanuvchidan emas),
    # lekin baribir tekshiriladi: SQL ga nom yopishtirilayotgani uchun
    # bu yerda ehtiyot bo'lish kerak.
    names = [name for name in tables if re.fullmatch(r"[a-z_][a-z0-9_]*", name)]
    if not names:
        return {}
    sql = " union all ".join(
        f"select '{name}' as table_name, count(*) as row_count from {name}"
        for name in names
    )
    counts = {name: 0 for name in tables}
    counts.update({r["table_name"]: int(r["row_count"] or 0) for r in _select(sql)})
    return counts


# --------------------------------------------------- 1-manba: `fuel_record`


FUEL_RECORD_SQL = """
select
    f.id::text                     as record_id,
    f.source_reference             as document_number,
    f.source_type                  as source_type,
    f.occurred_at                  as occurred_at,
    f.liters                       as liters,
    f.amount                       as amount,
    f.currency                     as currency,
    f.fuel_type                    as fuel_type,
    f.actual_distance_km           as distance_km,
    f.actual_engine_hours          as engine_hours,
    f.norm_liters_per100km         as norm_per100km,
    f.norm_liters_per_engine_hour  as norm_per_engine_hour,
    f.expected_fuel_liters         as expected_liters,
    f.deviation_percent            as db_deviation_percent,
    f.trip_id::text                as trip_id,
    v.id::text                     as vehicle_id,
    v.plate_number,
    v.brand,
    v.model,
    v.transport_type,
    d.id::text                     as driver_id,
    d.full_name                    as driver_name,
    d.table_number                 as driver_table_number
from fuel_record f
left join transport_vehicle v on v.id = f.vehicle_id
left join driver d            on d.id = f.driver_id
where f.occurred_at >= %s::date
  and f.occurred_at < (%s::date + 1)
order by f.occurred_at desc
limit %s
"""


def fetch_fuel_records(
    *, date_from: str, date_to: str, limit: int
) -> list[dict[str, Any]]:
    """`fuel_record` — bazadagi asosiy sarf jadvali.

    `expected_fuel_liters` ni ham olamiz: backend kutilgan sarfni o'zi
    hisoblab qo'yadi, ya'ni normani qayta hisoblash shart emas.

    `actual_engine_hours` kran va ekskavator uchun: ular 0 km yuradi, lekin
    turgan joyida yoqilg'i yoqadi, shuning uchun normasi masofaga emas,
    MOTOR-SOATga bog'langan (`fuel_norm.liters_per_engine_hour`).
    """
    return _select(FUEL_RECORD_SQL, (date_from, date_to, limit))


# ------------------------------------------------- 2-manba: yo'l varaqasi


WAYBILL_SQL = """
select
    w.id::text                         as record_id,
    w.waybill_number                   as document_number,
    w.status                           as status,
    w.waybill_type                     as waybill_type,
    w.issue_date,
    w.fuel_type,
    w.calculation_mode,
    w.motohours_worked,
    coalesce(w.closed_at, w.actual_return_at, w.actual_departure_at,
             w.issued_at, w.issue_date::timestamptz) as occurred_at,
    w.odometer_start_km,
    w.odometer_end_km,
    w.fuel_at_departure_liters,
    w.fuel_issued_liters,
    w.fuel_at_return_liters,
    w.fuel_consumed_liters,
    w.fuel_norm_liters,
    w.trip_id::text                    as trip_id,
    v.id::text                         as vehicle_id,
    v.plate_number,
    v.brand,
    v.model,
    v.transport_type,
    d.id::text                         as driver_id,
    d.full_name                        as driver_name,
    d.table_number                     as driver_table_number
from waybill w
left join transport_vehicle v on v.id = w.vehicle_id
left join driver d            on d.id = w.driver_id
where w.status = any(%s)
  and w.issue_date >= %s::date
  and w.issue_date <= %s::date
order by coalesce(w.closed_at, w.actual_return_at, w.issued_at,
                  w.issue_date::timestamptz) desc
limit %s
"""


def fetch_waybills(
    *,
    date_from: str,
    date_to: str,
    statuses: Sequence[str] = CLOSED_STATUSES,
    limit: int,
) -> list[dict[str, Any]]:
    """Yopilgan yo'l varaqalari — bakdagi qoldiq shu yerdan olinadi.

    `fuel_at_departure_liters` va `fuel_at_return_liters` — chiqishdagi va
    qaytishdagi bak qoldig'i, `fuel_issued_liters` — yo'lda quyilgani.
    Balans tenglamasi aynan shu uchtasidan quriladi.
    """
    return _select(WAYBILL_SQL, (list(statuses), date_from, date_to, limit))


# ------------------------------------------------------------------- Normalar


def fetch_norms(vehicle_ids: Sequence[str], *, on_date: str) -> dict[str, dict[str, Any]]:
    """Mashina bo'yicha amaldagi sarf normasi (`fuel_norm`).

    Ikki xil norma bo'lishi mumkin va ikkalasi ham olinadi:
      * `liters_per100km`        — yuradigan transport uchun;
      * `liters_per_engine_hour` — turgan joyida ishlaydigan texnika uchun.

    Norma davri `on_date` ga (tekshirilayotgan davr oxiriga) qarab tanlanadi,
    `current_date` ga emas: o'tgan oy tekshirilayotganda o'sha paytda amalda
    bo'lgan norma qo'llanishi kerak.
    """
    if not vehicle_ids:
        return {}
    rows = _select(
        """
        select distinct on (n.vehicle_id)
            n.vehicle_id::text as vehicle_id,
            n.liters_per100km,
            n.liters_per_engine_hour,
            n.tolerance_percent,
            n.fuel_type,
            n.effective_from,
            n.effective_to
        from fuel_norm n
        where n.vehicle_id = any(%s::uuid[])
          and n.effective_from <= %s::date
          and (n.effective_to is null or n.effective_to >= %s::date)
        order by n.vehicle_id, n.effective_from desc
        """,
        (list(vehicle_ids), on_date, on_date),
    )
    return {r["vehicle_id"]: r for r in rows}


def fetch_norm_candidates(vehicle_ids: Sequence[str], *, date_from: str, date_to: str) -> dict[str, list[dict[str, Any]]]:
    """All policies overlapping the report, selected per document later."""
    if not vehicle_ids:
        return {}
    rows = _select("""select n.vehicle_id::text,n.fuel_type,n.liters_per100km,
        n.liters_per_engine_hour,n.tolerance_percent,n.effective_from,n.effective_to
        from fuel_norm n where n.vehicle_id=any(%s::uuid[])
          and n.effective_from<=%s::date
          and (n.effective_to is null or n.effective_to>=%s::date)
        order by n.vehicle_id,n.effective_from,n.id""", (list(vehicle_ids),date_to,date_from))
    result = {}
    for row in rows:
        result.setdefault(row['vehicle_id'], []).append(row)
    return result


# -------------------------------------------------------------------- Limitlar


def fetch_limits() -> list[dict[str, Any]]:
    """Faol yoqilg'i limitlari.

    `subject_type` — `DRIVER` yoki `VEHICLE`, ya'ni limit haydovchiga ham,
    mashinaga ham qo'yilishi mumkin. `window_type` — `DAY` yoki `MONTH`.

    Sarf yig'indisi bu yerda emas, Python tomonda hisoblanadi: sarf ikki
    manbadan (`fuel_record` va `waybill`) kelishi mumkin, SQL da ularni
    birlashtirish esa manbalardan biri bo'sh bo'lganda ishlamay qolardi.
    """
    return _select(
        """
        select
            l.id::text          as limit_id,
            l.subject_type,
            l.subject_id::text  as subject_id,
            l.window_type,
            l.max_liters,
            l.max_amount,
            l.currency,
            l.fuel_type,
            l.note,
            v.plate_number,
            v.brand,
            v.model,
            v.transport_type,
            d.full_name         as driver_name,
            d.table_number      as driver_table_number
        from fuel_limit l
        left join transport_vehicle v
               on l.subject_type = 'VEHICLE' and v.id = l.subject_id
        left join driver d
               on l.subject_type = 'DRIVER'  and d.id = l.subject_id
        where l.active is true
          and l.max_liters is not null
        order by l.subject_type, l.window_type
        limit 20000
        """
    )
