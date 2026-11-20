"""Anomaliya qoidalari — sof arifmetika.

BU FAYLDA BIRORTA HAM O'YLAB TOPILGAN CHEGARA YO'Q. Har bir qoida yo
tenglamaning o'zi, yo bazadagi qiymat bilan solishtirish:

    qaytgan > chiqishdagi + quyilgan        mumkin emas    (chegara kerak emas)
    litr < 0                                mumkin emas    (chegara kerak emas)
    spidometr_oxiri < spidometr_boshi       mumkin emas    (chegara kerak emas)
    chiqish + quyilgan - qaytgan != sarf    zid            (chegara kerak emas)
    sarf > kutilgan x (1 + tolerans)        normadan oshdi (fuel_norm)
    davr yig'indisi > max_liters            limitdan oshdi (fuel_limit)

Norma bo'lmasa hukm chiqarilmaydi — `NO_NORM_DEFINED` deb yozib qo'yiladi,
xolos. Taxminiy tolerans bilan ayblash noto'g'ri bo'lardi.

Har bir qoida sof funksiya: kirish — bitta yozuv, chiqish — belgi yoki
`None`. Shuning uchun ularni bazasiz sinash mumkin.
"""

from __future__ import annotations

from oil_detection import texts
from oil_detection.texts import t

from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
import re
from typing import Any

#: Belgi turlari — daraja EMAS, tasnif. "Qanchalik yomon" degan baho
#: qo'yilmaydi, chunki uni bazadagi hech narsa aytmaydi.
KIND_IMPOSSIBLE = "IMPOSSIBLE"   # fizikaviy jihatdan mumkin emas
KIND_MISMATCH = "MISMATCH"       # ikki manba zid raqam ko'rsatyapti
KIND_OVER_NORM = "OVER_NORM"     # fuel_norm dan oshgan
KIND_OVER_LIMIT = "OVER_LIMIT"   # fuel_limit dan oshgan
KIND_DATA_GAP = "DATA_GAP"       # tekshirib bo'lmadi

#: Kod -> (turi, o'zbekcha sarlavha).
#: Kodlar imkon qadar bazadagi `fuel_record_risk_flag.risk_flag` enum'i bilan
#: bir xil nomlangan — hisobotni bazadagi belgilar bilan solishtirish oson bo'lsin.
#: Belgi kodi -> turi. NOMI (`title`) bu yerda emas, `texts.py` da uch
#: tilda (`flag.<KOD>`): javobdagi `code` va `kind` tarjima qilinmaydi,
#: `title` esa tanlangan tilda chiqadi.
FLAG_KIND: dict[str, str] = {
    "RETURN_EXCEEDS_AVAILABLE": KIND_IMPOSSIBLE,
    "NEGATIVE_VALUE": KIND_IMPOSSIBLE,
    "ODOMETER_BACKWARDS": KIND_IMPOSSIBLE,
    "BALANCE_MISMATCH": KIND_MISMATCH,
    "DB_DEVIATION_MISMATCH": KIND_MISMATCH,
    "SOURCE_LITERS_MISMATCH": KIND_MISMATCH,
    "CONSUMPTION_OVER_NORM": KIND_OVER_NORM,
    "LIMIT_EXCEEDED": KIND_OVER_LIMIT,
    "NO_NORM_DEFINED": KIND_DATA_GAP,
    "DISTANCE_UNKNOWN": KIND_DATA_GAP,
    "NO_TRIP_BOUND": KIND_DATA_GAP,
    "FUEL_ISSUED_UNKNOWN": KIND_DATA_GAP,
    "FUEL_UNIT_UNVERIFIED": KIND_DATA_GAP,
    "CALCULATION_MODE_UNSUPPORTED": KIND_DATA_GAP,
    "NORM_TOLERANCE_UNKNOWN": KIND_DATA_GAP,
}


def flag_title(code: str, lang: str = texts.DEFAULT_LANG) -> str:
    """Belgi nomining tanlangan tildagi matni.

    Noma'lum kod KODNING O'ZI bo'lib qaytadi — nom o'ylab topilmaydi.
    """
    key = f"flag.{code}"
    return t(lang, key) if key in texts.MESSAGES else code

def basis_label(basis: str | None, lang: str = texts.DEFAULT_LANG) -> str:
    """Sarf qaysi asosda o'lchangani — tanlangan tilda."""
    key = f"basis.{basis or ''}"
    return t(lang, key) if key in texts.MESSAGES else (basis or "")

#: `numeric(10,2)` ustunini qayta hisob bilan solishtirishda yaxlitlash
#: darajasi. Bu chegara emas — ustunning O'Z aniqligi.
DB_DECIMALS = 2


def make_flag(
    code: str,
    detail: str,
    evidence: dict[str, Any] | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    kind = FLAG_KIND.get(code, KIND_DATA_GAP)
    title = flag_title(code, lang)
    return {
        "code": code,
        "kind": kind,
        "title": title,
        "detail": detail,
        "evidence": evidence or {},
    }


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


# ------------------------------------------------------------------- Hodisa


@dataclass
class FuelEvent:
    """`fuel_record` va `waybill` dan keladigan umumiy ko'rinish.

    Manbalar ustunlari har xil, qoidalar esa bitta — shuning uchun avval
    umumiy shaklga keltiriladi. Ma'lumot yetishmasa maydon `None` bo'lib
    qoladi va unga bog'liq qoida oddiygina o'tkazib yuboriladi.
    """

    source: str
    record_id: str
    document_number: str | None = None
    occurred_at: datetime | None = None
    status: str | None = None
    fuel_type: str | None = None
    calculation_mode: str | None = None
    norm_date: date | None = None
    data_issues: list[str] = field(default_factory=list)
    trip_id: str | None = None

    vehicle: dict[str, Any] = field(default_factory=dict)
    driver: dict[str, Any] = field(default_factory=dict)

    # Xom qiymatlar
    odometer_start: float | None = None
    odometer_end: float | None = None
    fuel_start: float | None = None
    fuel_issued: float | None = None
    fuel_end: float | None = None
    reported_consumed: float | None = None
    doc_norm_liters: float | None = None
    src_distance_km: float | None = None
    src_engine_hours: float | None = None
    src_norm_per100km: float | None = None
    src_norm_per_engine_hour: float | None = None
    src_expected_liters: float | None = None
    db_deviation_percent: float | None = None

    # Hisoblangan
    distance_km: float | None = None
    engine_hours: float | None = None
    balance_consumed: float | None = None
    consumed: float | None = None
    basis: str | None = None
    actual_rate: float | None = None
    norm_rate: float | None = None
    norm_source: str | None = None
    expected_liters: float | None = None
    tolerance_percent: float | None = None
    allowed_liters: float | None = None
    deviation_percent: float | None = None
    excess_liters: float | None = None

    #: Bir voqeaning ikki jadvaldagi nusxalarini bog'lovchi kalit.
    #: `assign_groups` to'ldiradi.
    group_key: str = ""
    #: Bu yozuvning sarfi yig'indiga (limit, reyting) qo'shiladimi.
    #: Guruhda bittasi `True` bo'ladi — qolganlari takror.
    counts_consumption: bool = True

    def metrics(self) -> dict[str, Any]:
        by_distance = self.basis in ("distance", "waybill_norm")
        by_hour = self.basis == "engine_hour"
        return {
            "basis": self.basis,
            "distance_km": _r(self.distance_km),
            "engine_hours": _r(self.engine_hours),
            "consumed_liters": _r(self.consumed),
            "balance_consumed_liters": _r(self.balance_consumed),
            "reported_consumed_liters": None if 'FUEL_UNIT_UNVERIFIED' in self.data_issues else _r(self.reported_consumed),
            "expected_liters": _r(self.expected_liters),
            "tolerance_percent": _r(self.tolerance_percent, 2),
            "allowed_liters": _r(self.allowed_liters),
            "actual_per100km": _r(self.actual_rate, 2) if by_distance else None,
            "norm_per100km": _r(self.norm_rate, 2) if by_distance else None,
            "actual_per_engine_hour": _r(self.actual_rate, 2) if by_hour else None,
            "norm_per_engine_hour": _r(self.norm_rate, 2) if by_hour else None,
            "deviation_percent": _r(self.deviation_percent, 2),
            "excess_liters": _r(self.excess_liters),
        }


def _vehicle_of(
    row: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> dict[str, Any]:
    return {
        "id": row.get("vehicle_id"),
        "plate_number": row.get("plate_number"),
        "brand": row.get("brand"),
        "model": row.get("model"),
        # Kod emas, NOM: boshqa modullardagi bilan bir xil ko'rinish.
        "transport_type": texts.transport_name(row.get("transport_type"), lang),
    }


def _driver_of(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("driver_id"),
        "full_name": row.get("driver_name"),
        "table_number": row.get("driver_table_number"),
    }


def event_from_fuel_record(
    row: dict[str, Any], to_float, lang: str = texts.DEFAULT_LANG
) -> FuelEvent:
    return FuelEvent(
        source="fuel_record",
        record_id=str(row.get("record_id")),
        document_number=row.get("document_number"),
        occurred_at=row.get("occurred_at"),
        status=row.get("source_type"),
        fuel_type=row.get("fuel_type"),
        norm_date=row.get('occurred_at').astimezone(timezone(timedelta(hours=5))).date() if isinstance(row.get('occurred_at'), datetime) and row['occurred_at'].tzinfo else None,
        trip_id=row.get("trip_id"),
        vehicle=_vehicle_of(row, lang),
        driver=_driver_of(row),
        reported_consumed=to_float(row.get("liters")),
        src_distance_km=to_float(row.get("distance_km")),
        src_engine_hours=to_float(row.get("engine_hours")),
        src_norm_per100km=to_float(row.get("norm_per100km")),
        src_norm_per_engine_hour=to_float(row.get("norm_per_engine_hour")),
        src_expected_liters=to_float(row.get("expected_liters")),
        db_deviation_percent=to_float(row.get("db_deviation_percent")),
    )


def event_from_waybill(
    row: dict[str, Any], to_float, lang: str = texts.DEFAULT_LANG
) -> FuelEvent:
    return FuelEvent(
        source="waybill",
        record_id=str(row.get("record_id")),
        document_number=row.get("document_number"),
        occurred_at=row.get("occurred_at"),
        status=row.get("status"),
        fuel_type=row.get('fuel_type'),
        calculation_mode=row.get('calculation_mode'),
        norm_date=row.get('issue_date'),
        trip_id=row.get("trip_id"),
        vehicle=_vehicle_of(row, lang),
        driver=_driver_of(row),
        odometer_start=to_float(row.get("odometer_start_km")),
        odometer_end=to_float(row.get("odometer_end_km")),
        fuel_start=to_float(row.get("fuel_at_departure_liters")),
        fuel_issued=to_float(row.get("fuel_issued_liters")),
        fuel_end=to_float(row.get("fuel_at_return_liters")),
        reported_consumed=to_float(row.get("fuel_consumed_liters")),
        doc_norm_liters=to_float(row.get("fuel_norm_liters")),
        src_engine_hours=to_float(row.get('motohours_worked')),
    )


# --------------------------------------------------------------- Hisob-kitob

_PETROL_GRADE_RE = re.compile(r"^(?:petrol|benzin(?:\s*ai)?|ai)[_\s-]*(80|92|95|98)$", re.I)


def canonical_fuel(value: str | None) -> str:
    """Normalize equivalent fuel labels across tables without losing octane grades."""
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""
    lowered = raw.casefold()
    if lowered in ("diesel", "dizel"):
        return "DIESEL"
    if lowered in ("cng", "metan", "methane"):
        return "CNG"
    if lowered in ("lpg", "propan", "propane"):
        return "LPG"
    if lowered == "lng":
        return "LNG"
    if lowered in ("gas", "gaz"):
        return "GAS"
    if lowered in ("petrol", "benzin"):
        return "PETROL"
    match = _PETROL_GRADE_RE.match(raw)
    if match:
        return f"PETROL_{match.group(1)}"
    return raw.upper()


def fuel_matches_policy(policy_fuel: str | None, event_fuel: str | None) -> bool:
    """Return True when a policy fuel filter covers the event's fuel."""
    expected = canonical_fuel(policy_fuel)
    actual = canonical_fuel(event_fuel)
    if not expected:
        return True
    if not actual:
        return False
    return expected == actual or (expected == "PETROL" and actual.startswith("PETROL_"))


def match_fuel_norms(norms: list[dict[str, Any]], event_fuel: str | None) -> list[dict[str, Any]]:
    """Prefer exact canonical fuel matches; fall back to generic PETROL only for PETROL_* grades."""
    target = canonical_fuel(event_fuel)
    if not target:
        return []
    exact = [row for row in norms if canonical_fuel(row.get("fuel_type")) == target]
    if exact or not target.startswith("PETROL_"):
        return exact
    return [row for row in norms if canonical_fuel(row.get("fuel_type")) == "PETROL"]


def select_norm(event: FuelEvent, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match the documented fuel and event date; never borrow a period-end policy."""
    day = event.norm_date
    if isinstance(day, str):
        try: day = date.fromisoformat(day[:10])
        except ValueError: return None
    if day is None or not canonical_fuel(event.fuel_type):
        return None
    active = []
    for row in candidates:
        begin = row.get('effective_from'); end = row.get('effective_to')
        if isinstance(begin, str): begin = date.fromisoformat(begin[:10])
        if isinstance(end, str): end = date.fromisoformat(end[:10])
        if begin is not None and begin <= day and (end is None or day <= end):
            active.append(row)
    matches = match_fuel_norms(active, event.fuel_type)
    policies = {(r.get('liters_per100km'),r.get('liters_per_engine_hour'),r.get('tolerance_percent')) for r in matches}
    return matches[0] if len(policies) == 1 else None


def compute(event: FuelEvent, norm_row: dict[str, Any] | None, to_float) -> FuelEvent:
    """Hosila ko'rsatkichlarni to'ldiradi. Qoidalardan OLDIN chaqiriladi."""
    # 1. Masofa: manbadagi tayyor qiymat, bo'lmasa spidometr farqi.
    if event.src_distance_km is not None and event.src_distance_km > 0:
        event.distance_km = event.src_distance_km
    elif event.odometer_start is not None and event.odometer_end is not None:
        event.distance_km = event.odometer_end - event.odometer_start
    event.engine_hours = event.src_engine_hours

    # 2. Balans — BAKDAGI QOLDIQDAN, hujjatdagi songa ishonmasdan.
    #
    # QUYILGAN NOMA'LUM BO'LSA BALANS HISOBLANMAYDI. `fuel_issued` ning
    # `None` i "quyilmagan" degani emas, "bilmaymiz" degani. Uni nolga
    # aylantirish butun zanjirni buzadi:
    #     balans -> sarf -> sarf tezligi -> normadan chetlanish
    # Bilinmagan katak o'rniga taxmin qo'yilsa, hisobot uni O'LCHOVDEK
    # ko'rsatadi. Bo'shliqning o'zi `rule_data_gaps` da belgilanadi.
    if (
        event.fuel_start is not None
        and event.fuel_end is not None
        and event.fuel_issued is not None
    ):
        event.balance_consumed = event.fuel_start + event.fuel_issued - event.fuel_end

    # 3. Sarf: hujjatdagi son bor bo'lsa o'shani olamiz (qoidalar ikkalasini
    #    solishtiradi), bo'lmasa balansdan chiqqanini.
    event.consumed = (
        event.reported_consumed if event.reported_consumed is not None else event.balance_consumed
    )
    fuel = canonical_fuel(event.fuel_type)
    if not fuel or fuel in ('CNG', 'LNG', 'GAS'):
        event.data_issues.append('FUEL_UNIT_UNVERIFIED')
        event.consumed = event.balance_consumed = None
        return event
    mode = str(event.calculation_mode or '').upper()
    if event.source == 'waybill' and mode not in ('KM_ONLY','KM','DISTANCE','MOTOHOURS_ONLY','ENGINE_HOUR','ENGINE_HOURS'):
        event.data_issues.append('CALCULATION_MODE_UNSUPPORTED')
        return event

    # 4. Tolerans — FAQAT bazadagi normadan. Norma yo'q bo'lsa tolerans ham
    #    yo'q, ya'ni normadan chetlanish umuman tekshirilmaydi.
    if norm_row is not None:
        event.tolerance_percent = to_float(norm_row.get("tolerance_percent"))

    norm_per100 = to_float((norm_row or {}).get("liters_per100km")) or event.src_norm_per100km
    norm_per_hour = (
        to_float((norm_row or {}).get("liters_per_engine_hour")) or event.src_norm_per_engine_hour
    )
    if norm_row is not None:
        event.norm_source = "fuel_norm"
    elif event.src_norm_per100km or event.src_norm_per_engine_hour:
        event.norm_source = "fuel_record"

    has_distance = event.distance_km is not None and event.distance_km > 0
    has_hours = event.engine_hours is not None and event.engine_hours > 0
    if event.source == 'waybill':
        has_distance = has_distance and mode in ('KM_ONLY','KM','DISTANCE')
        has_hours = has_hours and mode in ('MOTOHOURS_ONLY','ENGINE_HOUR','ENGINE_HOURS')

    # 5. Qaysi asosda o'lchaymiz — ishonch tartibida.
    if event.src_expected_liters and event.src_expected_liters > 0:
        # Backend kutilgan sarfni o'zi hisoblab qo'ygan — qayta hisoblashning
        # ma'nosi yo'q, ayirmaning o'zi yetadi.
        event.basis = "expected"
        event.expected_liters = event.src_expected_liters
        event.norm_source = event.norm_source or "fuel_record"
    elif has_distance and norm_per100:
        event.basis = "distance"
        event.norm_rate = norm_per100
        event.expected_liters = norm_per100 * event.distance_km / 100
        if event.consumed is not None:
            event.actual_rate = event.consumed / event.distance_km * 100
    elif has_hours and norm_per_hour:
        # Kran, ekskavator va shunga o'xshash texnika: 0 km yuradi, lekin
        # turgan joyida yoqilg'i yoqadi — normasi motor-soatga bog'langan.
        event.basis = "engine_hour"
        event.norm_rate = norm_per_hour
        event.expected_liters = norm_per_hour * event.engine_hours
        if event.consumed is not None:
            event.actual_rate = event.consumed / event.engine_hours
    elif has_distance and event.doc_norm_liters is not None:
        # Yo'l varaqasidagi norma LITRDA yozilgan (butun reysga).
        event.basis = "waybill_norm"
        event.norm_source = "waybill"
        event.expected_liters = event.doc_norm_liters
        event.norm_rate = event.doc_norm_liters / event.distance_km * 100
        if event.consumed is not None:
            event.actual_rate = event.consumed / event.distance_km * 100

    # 6. Ruxsat etilgan chegara va chetlanish.
    #
    # MANFIY SARFDAN HOSILA CHIQARILMAYDI. Sarf manfiy bo'lsa (masalan
    # chiqishda 50 L, qaytishda 252 L), bu kiritish xatosi va u alohida
    # belgilanadi. Undan "100 km ga -0.01 L" yoki "chetlanish -185.96%"
    # kabi son chiqarish natijani chalg'itadi — hisobotda ko'rilganda
    # xuddi haqiqiy o'lchovdek ko'rinadi.
    #
    # Bu chegara emas: manfiy sarfdan sarf tezligini hisoblab bo'lmaydi.
    if event.consumed is not None and event.consumed < 0:
        event.actual_rate = None
        return event

    if event.expected_liters and event.expected_liters > 0:
        if event.tolerance_percent is not None and event.tolerance_percent >= 0:
            event.allowed_liters = event.expected_liters * (1 + event.tolerance_percent / 100)
        else:
            event.data_issues.append('NORM_TOLERANCE_UNKNOWN')
        if event.consumed is not None:
            event.excess_liters = event.consumed - event.expected_liters
            event.deviation_percent = event.excess_liters / event.expected_liters * 100

    return event


# ------------------------------------------------------------------ Qoidalar


def rule_balance(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Hujjatdagi sarf bakdagi qoldiqqa mos kelmasa.

    YO'L QO'YILMAYDI: farq bo'lsa — bor. Raqamlarni qo'lda to'g'rilashda
    odatda faqat bitta katak o'zgartiriladi va tenglama buziladi.
    """
    if event.balance_consumed is None or event.reported_consumed is None:
        return None
    diff = event.reported_consumed - event.balance_consumed
    if diff == 0:
        return None
    return make_flag(
        "BALANCE_MISMATCH",
        t(lang, "detail.balance_mismatch",
          reported=f"{event.reported_consumed:g}",
          balance=f"{event.balance_consumed:g}", diff=f"{diff:+g}",
          start=f"{event.fuel_start or 0:g}", issued=f"{event.fuel_issued or 0:g}",
          end=f"{event.fuel_end or 0:g}"),
        {
            "fuel_at_departure_liters": event.fuel_start,
            "fuel_issued_liters": event.fuel_issued,
            "fuel_at_return_liters": event.fuel_end,
            "reported_consumed_liters": event.reported_consumed,
            "balance_consumed_liters": _r(event.balance_consumed),
            "difference_liters": _r(diff),
        },
    lang=lang,
    )


def rule_return_exceeds_available(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Qaytishdagi bak qoldig'i chiqishdagi + quyilgandan ko'p bo'lsa.

    Bu fizikaviy jihatdan mumkin emas: yo'lda hujjatsiz quyilgan yoki
    ko'rsatkich soxtalashtirilgan.

    QUYILGAN NOMA'LUM BO'LSA HUKM CHIQARILMAYDI. Belgi haydovchini ayblaydi
    ("hujjatsiz quyish"), shuning uchun u faqat quyilgan miqdor ANIQ
    bo'lgandagina qo'yiladi. `fuel_issued is None` — bu "quyilmagan" emas,
    "yozilmagan": yo'lda quyilgan bo'lishi ham mumkin. Nolga aylantirilsa
    aybsiz yozuv `IMPOSSIBLE` tamg'asini olardi.

    Xuddi `NO_NORM_DEFINED` kabi: bo'shliq hukm emas, bo'shliq deb yoziladi
    (`FUEL_ISSUED_UNKNOWN`, `rule_data_gaps`).
    """
    if event.fuel_start is None or event.fuel_end is None:
        return None
    if event.fuel_issued is None:
        return None
    available = event.fuel_start + event.fuel_issued
    if event.fuel_end <= available:
        return None
    return make_flag(
        "RETURN_EXCEEDS_AVAILABLE",
        t(lang, "detail.return_exceeds", end=f"{event.fuel_end:g}",
          available=f"{available:g}", start=f"{event.fuel_start:g}",
          issued=f"{event.fuel_issued:g}",
          over=f"{event.fuel_end - available:g}"),
        {
            "fuel_at_departure_liters": event.fuel_start,
            "fuel_issued_liters": event.fuel_issued,
            "fuel_at_return_liters": event.fuel_end,
            "available_liters": _r(available),
            "excess_liters": _r(event.fuel_end - available),
        },
    lang=lang,
    )


def rule_negative_values(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Manfiy litr — kiritish xatosi yoki buzib yozish."""
    bad: dict[str, Any] = {}
    for name, value in (
        ("fuel_at_departure_liters", event.fuel_start),
        ("fuel_issued_liters", event.fuel_issued),
        ("fuel_at_return_liters", event.fuel_end),
        ("consumed_liters", event.consumed),
    ):
        if value is not None and value < 0:
            bad[name] = value
    if not bad:
        return None
    return make_flag(
        "NEGATIVE_VALUE",
        t(lang, "detail.negative_value",
          values=", ".join(f"{k} = {v:g}" for k, v in bad.items())),
        bad,
    lang=lang,
    )


def rule_odometer(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Spidometr orqaga qaytgan bo'lsa — mumkin emas.

    Masofaning KATTALIGI tekshirilmaydi: "bir hujjatda eng ko'pi shuncha km"
    degan qoida bazada yo'q, uni o'ylab topish esa uzoq masofa reyslarini
    noto'g'ri belgilardi.
    """
    if event.odometer_start is None or event.odometer_end is None:
        return None
    if event.odometer_end >= event.odometer_start:
        return None
    return make_flag(
        "ODOMETER_BACKWARDS",
        t(lang, "detail.odometer_backwards", end=f"{event.odometer_end:g}",
          start=f"{event.odometer_start:g}"),
        {
            "odometer_start_km": event.odometer_start,
            "odometer_end_km": event.odometer_end,
            "difference_km": _r(event.odometer_end - event.odometer_start),
        },
    lang=lang,
    )


def rule_consumption_vs_norm(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Sarf bazadagi normadan oshdimi.

    Ikki holat bor, uchinchisi yo'q: `tolerance_percent` ichida yoki undan
    tashqarida. "Jiddiy" degan alohida daraja bazada belgilanmagan, shuning
    uchun bu yerda ham yo'q.
    """
    if event.allowed_liters is None or event.consumed is None:
        return None
    if event.consumed <= event.allowed_liters:
        return None

    tolerance = event.tolerance_percent or 0.0
    if event.basis == "engine_hour" and event.actual_rate and event.norm_rate:
        scale = t(lang, "detail.scale_engine_hour",
                  hours=f"{event.engine_hours:g}",
                  actual=f"{event.actual_rate:.2f}", norm=f"{event.norm_rate:g}")
    elif event.basis in ("distance", "waybill_norm") and event.actual_rate and event.norm_rate:
        scale = t(lang, "detail.scale_distance", km=f"{event.distance_km:g}",
                  actual=f"{event.actual_rate:.2f}", norm=f"{event.norm_rate:g}")
    else:
        scale = t(lang, "detail.scale_expected", consumed=f"{event.consumed:g}",
                  expected=f"{event.expected_liters:g}")

    return make_flag(
        "CONSUMPTION_OVER_NORM",
        t(lang, "detail.over_norm", scale=scale, tolerance=f"{tolerance:g}",
          allowed=f"{event.allowed_liters:.2f}", consumed=f"{event.consumed:g}",
          excess=f"{event.excess_liters:.2f}",
          percent=f"{event.deviation_percent:+.2f}"),
        {
            "basis": event.basis,
            "basis_label": basis_label(event.basis, lang),
            "consumed_liters": _r(event.consumed),
            "expected_liters": _r(event.expected_liters),
            "tolerance_percent": _r(tolerance, 2),
            "allowed_liters": _r(event.allowed_liters),
            "actual_rate": _r(event.actual_rate, 2),
            "norm_rate": _r(event.norm_rate, 2),
            "norm_source": event.norm_source,
            "deviation_percent": _r(event.deviation_percent, 2),
            "excess_liters": _r(event.excess_liters),
        },
    lang=lang,
    )


def rule_db_deviation_mismatch(event: FuelEvent, lang: str = texts.DEFAULT_LANG) -> dict[str, Any] | None:
    """Bazadagi `deviation_percent` bilan qayta hisobni solishtiradi.

    Ikki mustaqil hisob bir xil chiqishi kerak. Farq bo'lsa — norma yozuvdan
    keyin o'zgargan yoki backend hisobi eskirgan.

    Solishtirish ustunning O'Z aniqligida (`numeric(10,2)`) — bu o'ylab
    topilgan yo'l qo'yish emas, ustunda undan aniqroq son saqlanmaydi.
    """
    if event.source != "fuel_record" or event.db_deviation_percent is None:
        return None
    if event.deviation_percent is None:
        return None
    ours = round(event.deviation_percent, DB_DECIMALS)
    theirs = round(event.db_deviation_percent, DB_DECIMALS)
    if ours == theirs:
        return None
    return make_flag(
        "DB_DEVIATION_MISMATCH",
        t(lang, "detail.db_deviation", theirs=f"{theirs:+.2f}",
          ours=f"{ours:+.2f}"),
        {
            "db_deviation_percent": theirs,
            "recomputed_deviation_percent": ours,
            "consumed_liters": _r(event.consumed),
            "expected_liters": _r(event.expected_liters),
        },
    lang=lang,
    )


def rule_data_gaps(
    event: FuelEvent, lang: str = texts.DEFAULT_LANG
) -> list[dict[str, Any]]:
    """Tekshiruvni imkonsiz qiladigan bo'shliqlar.

    Ular ham hisobotga kiradi: "anomaliya topilmadi" va "tekshirib bo'lmadi"
    bir xil narsa emas. Nazoratchi qaysi hujjat to'ldirilmaganini ko'rishi kerak.
    """
    flags: list[dict[str, Any]] = []
    for code in event.data_issues:
        flags.append(make_flag(code, t(lang, 'detail.'+code.lower()), {}, lang=lang))
    if not (event.distance_km or 0) > 0 and not (event.engine_hours or 0) > 0:
        flags.append(
            make_flag(
                "DISTANCE_UNKNOWN",
                t(lang, "detail.distance_unknown"),
                {
                    "odometer_start_km": event.odometer_start,
                    "odometer_end_km": event.odometer_end,
                    "engine_hours": event.engine_hours,
                },
                lang=lang,
            )
        )
    if not event.expected_liters:
        flags.append(
            make_flag(
                "NO_NORM_DEFINED",
                t(lang, "detail.no_norm"),
                {"vehicle_id": event.vehicle.get("id")},
            lang=lang,
            )
        )
    if not event.trip_id:
        flags.append(
            make_flag(
                "NO_TRIP_BOUND",
                t(lang, "detail.no_trip"),
                {},
            lang=lang,
            )
        )
    # Bak qoldig'i ikki tomondan yozilgan, lekin yo'lda quyilgani yo'q:
    # balansni yopib bo'lmaydi. Bu AYBLOV EMAS — aynan shuning uchun
    # `RETURN_EXCEEDS_AVAILABLE` o'rniga shu belgi qo'yiladi.
    if (
        event.fuel_start is not None
        and event.fuel_end is not None
        and event.fuel_issued is None
    ):
        flags.append(
            make_flag(
                "FUEL_ISSUED_UNKNOWN",
                t(lang, "detail.fuel_issued_unknown"),
                {
                    "fuel_at_departure_liters": event.fuel_start,
                    "fuel_at_return_liters": event.fuel_end,
                },
            lang=lang,
            )
        )
    return flags


def evaluate_event(
    event: FuelEvent, lang: str = texts.DEFAULT_LANG
) -> list[dict[str, Any]]:
    """Bitta yozuvga barcha qoidalarni qo'llaydi."""
    flags: list[dict[str, Any]] = []
    if 'FUEL_UNIT_UNVERIFIED' in event.data_issues:
        odometer = rule_odometer(event, lang)
        values = {'departure_quantity': event.fuel_start, 'issued_quantity': event.fuel_issued,
                  'return_quantity': event.fuel_end, 'reported_consumption_quantity': event.reported_consumed}
        negative = {key:value for key,value in values.items() if value is not None and value < 0}
        if negative:
            flags.append(make_flag('NEGATIVE_VALUE', t(lang,'detail.negative_value',
                values=', '.join(f'{key} = {value:g}' for key,value in negative.items())),
                {'recorded_quantities':negative,'unit':'UNVERIFIED'},lang=lang))
        return flags + rule_data_gaps(event, lang) + ([odometer] if odometer else [])
    for rule in (
        rule_negative_values,
        rule_odometer,
        rule_return_exceeds_available,
        rule_balance,
        rule_consumption_vs_norm,
        rule_db_deviation_mismatch,
    ):
        flag = rule(event, lang)
        if flag:
            flags.append(flag)
    flags.extend(rule_data_gaps(event, lang))
    return flags


# -------------------------------------------------------------------- Limit


def limit_flag(
    *,
    limit_row: dict[str, Any],
    used_liters: float,
    bucket_label: str,
    record_count: int,
    to_float,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Kunlik yoki oylik limitdan oshib ketish.

    Bu qoida BITTA HUJJATDA emas, DAVR bo'yicha ishlaydi: har bir reys
    alohida normal bo'lishi mumkin, lekin yig'indi limitdan oshadi.
    """
    max_liters = to_float(limit_row.get("max_liters")) or 0.0
    over = used_liters - max_liters
    window = t(lang, "misc.daily" if limit_row.get("window_type") == "DAY"
               else "misc.monthly")
    subject = t(lang, "misc.driver" if limit_row.get("subject_type") == "DRIVER"
                else "misc.vehicle")
    return make_flag(
        "LIMIT_EXCEEDED",
        t(lang, "detail.limit_exceeded", subject=subject, window=window,
          max=f"{max_liters:g}", period=bucket_label, count=record_count,
          used=f"{used_liters:g}", over=f"{over:g}"),
        {
            "limit_id": limit_row.get("limit_id"),
            "subject_type": limit_row.get("subject_type"),
            "window_type": limit_row.get("window_type"),
            "period": bucket_label,
            "max_liters": max_liters,
            "used_liters": _r(used_liters),
            "over_liters": _r(over),
            "record_count": record_count,
            "fuel_type": limit_row.get("fuel_type"),
            "note": limit_row.get("note"),
        },
    lang=lang,
    )


# ------------------------------------------------------- Yo'qolgan litrlar


#: Belgi -> `evidence` dagi qaysi maydon "hisobdan tashqari litr" ekanini
#: ko'rsatadi. Reyting shu litrlar bo'yicha saralanadi — o'ylab topilgan
#: ball bilan emas, o'lchangan miqdor bilan.
UNACCOUNTED_FIELDS = {
    "RETURN_EXCEEDS_AVAILABLE": "excess_liters",
    "BALANCE_MISMATCH": "difference_liters",
}


def unaccounted_liters(flags: list[dict[str, Any]]) -> float:
    """Hujjat raqamlari zid bo'lgani uchun hisobdan chiqib ketgan litr."""
    total = 0.0
    for flag in flags:
        key = UNACCOUNTED_FIELDS.get(flag["code"])
        if not key:
            continue
        value = flag["evidence"].get(key)
        if isinstance(value, (int, float)):
            total += abs(value)
    return total


def kinds_of(flags: list[dict[str, Any]]) -> list[str]:
    """Yozuvda qanday turdagi muammolar borligi (tartibi barqaror)."""
    order = [KIND_IMPOSSIBLE, KIND_MISMATCH, KIND_OVER_NORM, KIND_OVER_LIMIT, KIND_DATA_GAP]
    present = {f["kind"] for f in flags}
    return [k for k in order if k in present]


def has_finding(flags: list[dict[str, Any]]) -> bool:
    """Yozuvda haqiqiy topilma bormi (ma'lumot yetishmasligi topilma emas)."""
    return any(f["kind"] != KIND_DATA_GAP for f in flags)


# ------------------------------------------------- Takrorlanishning oldini olish


def _key_of(event: FuelEvent) -> str:
    """Bir voqeaning ikki jadvaldagi nusxalarini bog'lovchi kalit.

    Bitta reys ham `waybill` ga (mexanik yozadi), ham `fuel_record` ga (ERP
    yozadi) tushishi mumkin. Ikkalasini alohida sanash sarf yig'indisini
    IKKI BARAVAR qilib yuboradi va soxta limit buzilishini beradi.

    Bog'lash yo'llari:
      1. `trip_id` — ikkala jadvalda ham bor;
      2. hujjat raqami — `fuel_record.source_reference` yo'l varaqasi
         raqamini saqlaydi.
    Ikkalasi ham bo'lmasa yozuv yolg'iz qoladi (o'z id'si bilan).
    """
    if event.trip_id:
        return f"trip:{event.trip_id}"
    if event.document_number:
        return f"doc:{event.document_number}"
    return f"row:{event.source}:{event.record_id}"


def assign_groups(events: list[FuelEvent]) -> int:
    """Takror yozuvlarni belgilaydi. Nechta guruhda takror borligini qaytaradi.

    Sarf yig'indisiga guruhdan FAQAT BITTA yozuv qo'shiladi. Tanlov:
    `waybill` ustun turadi, chunki uning `fuel_consumed_liters` ustuni
    aynan SARFni bildiradi; `fuel_record.liters` esa quyish yozuvi ham
    bo'lishi mumkin (`source_type` ga qarab).

    Qolgan yozuvlar o'chirilmaydi — ularning o'z qoidalari baribir
    tekshiriladi, faqat litri qayta sanalmaydi.
    """
    groups: dict[str, list[FuelEvent]] = {}
    for event in events:
        event.group_key = _key_of(event)
        groups.setdefault(event.group_key, []).append(event)

    duplicated = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        duplicated += 1
        chosen = next(
            (e for e in members if e.source == "waybill" and e.consumed is not None),
            next((e for e in members if e.consumed is not None), members[0]),
        )
        for event in members:
            event.counts_consumption = event is chosen
    return duplicated


def source_mismatch_flag(
    members: list[FuelEvent], lang: str = texts.DEFAULT_LANG
) -> dict[str, Any] | None:
    """Bir voqeani ikki manba turlicha yozgan bo'lsa.

    Bu — ikki MUSTAQIL manbaning bir-birini tekshirishi: yo'l varaqasini
    mexanik qo'lda to'ldiradi, `fuel_record` ga ERP yozadi. Ular zid bo'lsa,
    biri noto'g'ri.
    """
    reported = [(e.source, e.consumed) for e in members if e.consumed is not None]
    if len(reported) < 2:
        return None
    values = {round(v, 3) for _, v in reported}
    if len(values) < 2:
        return None
    parts = ", ".join(f"{src} = {val:g} L" for src, val in reported)
    biggest, smallest = max(values), min(values)
    return make_flag(
        "SOURCE_LITERS_MISMATCH",
        t(lang, "detail.source_mismatch", parts=parts,
          diff=f"{biggest - smallest:g}"),
        {
            "sources": {src: val for src, val in reported},
            "difference_liters": _r(biggest - smallest),
        },
    lang=lang,
    )
