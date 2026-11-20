"""Yoqilg'i tekshiruvi — orkestrator.

BITTA KIRISH NUQTASI: `report(date_from, date_to)`. Bitta JSON qaytaradi va
ichida uchta kesim bo'ladi:

    vehicles   — qaysi MASHINA ortiqcha sarflayapti (saralangan)
    drivers    — qaysi HAYDOVCHI (saralangan)
    anomalies  — o'sha raqam QAYSI HUJJATDAN chiqqani

Uchalasi bir xil ma'lumot va bir xil qoidalar ustida quriladi, shuning uchun
baza bir marta o'qiladi.

SARALASH O'LCHANGAN LITR BO'YICHA, o'ylab topilgan ball bilan emas:
    1) unaccounted_liters — hujjat raqamlari zid bo'lgani uchun hisobdan
       chiqib ketgan litr;
    2) over_limit_liters  — `fuel_limit` dan oshgani;
    3) excess_liters      — `fuel_norm` dan ortiqchasi.
Birinchisi oldinda, chunki normadan ortiqcha sarflashning texnik sababi
bo'lishi mumkin, hujjatda litr yo'qolishining esa yo'q.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from oil_detection import config, queries, rules
from oil_detection import texts
from oil_detection.explain import template_explanation
from oil_detection.texts import t
from oil_detection.queries import to_float

logger = logging.getLogger(__name__)


def _anomaly(
    *,
    source: str,
    record_id: str,
    flags: list[dict[str, Any]],
    vehicle: dict[str, Any],
    driver: dict[str, Any],
    occurred_at: Any = None,
    document_number: str | None = None,
    lang: str = texts.DEFAULT_LANG,
    metrics: dict[str, Any] | None = None,
    unaccounted: float = 0.0,
    over_limit: float = 0.0,
    excess: float = 0.0,
) -> dict[str, Any]:
    anomaly = {
        "id": f"{source}:{record_id}",
        "source": source,
        "document_number": document_number,
        "occurred_at": occurred_at,
        "kinds": rules.kinds_of(flags),
        "unaccounted_liters": round(unaccounted, 3),
        "over_limit_liters": round(over_limit, 3),
        "excess_liters": round(excess, 3),
        "vehicle": vehicle,
        "driver": driver,
        "metrics": metrics or {},
        "flags": flags,
        "explanation": "",
        "explanation_source": "template",
    }
    anomaly["explanation"] = template_explanation(anomaly, lang)
    return anomaly


def _anomaly_sort_key(anomaly: dict[str, Any]) -> tuple[float, float, float, float]:
    occurred = anomaly.get("occurred_at")
    stamp = 0.0
    if isinstance(occurred, datetime):
        # Sana ba'zan tz'siz keladi — solishtirishda TypeError bermasin.
        aware = occurred if occurred.tzinfo else occurred.replace(tzinfo=timezone.utc)
        stamp = aware.timestamp()
    return (
        -anomaly["unaccounted_liters"],
        -anomaly["over_limit_liters"],
        -anomaly["excess_liters"],
        -stamp,
    )


# ------------------------------------------------------------------- Yig'ish


@dataclass
class Collected:
    events: list[rules.FuelEvent] = field(default_factory=list)
    flags_by_event: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    limits: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    duplicate_groups: int = 0


def _collect(
    date_from: str, date_to: str, row_limit: int,
    lang: str = texts.DEFAULT_LANG,
) -> Collected:
    """Bazani bir marta o'qiydi va qoidalarni qo'llaydi."""
    out = Collected(counts=queries.row_counts())

    if out.counts.get("fuel_record"):
        rows = queries.fetch_fuel_records(
            date_from=date_from, date_to=date_to, limit=row_limit)
        # Chegaraga yetilsa natija to'liq emas — buni yashirib bo'lmaydi.
        if len(rows) >= row_limit:
            out.notes.append(
                t(lang, "note.row_limit", table="fuel_record", limit=row_limit)
            )
        out.events += [rules.event_from_fuel_record(row, to_float, lang) for row in rows]
        out.sources_used.append("fuel_record")

    if out.counts.get("waybill"):
        rows = queries.fetch_waybills(date_from=date_from, date_to=date_to, limit=row_limit)
        if len(rows) >= row_limit:
            out.notes.append(
                t(lang, "note.row_limit", table="waybill", limit=row_limit)
            )
        out.events += [rules.event_from_waybill(row, to_float, lang) for row in rows]
        out.sources_used.append("waybill")

    if out.events:
        vehicle_ids = sorted({e.vehicle.get("id") for e in out.events if e.vehicle.get("id")})
        # Norma BITTA so'rovda hamma mashina uchun olinadi — har bir yozuvga
        # alohida so'rov yuborish bazani bekorga yuklardi (N+1).
        norms = (
            queries.fetch_norm_candidates(vehicle_ids, date_from=date_from, date_to=date_to)
            if out.counts.get("fuel_norm") else {}
        )
        if norms:
            out.sources_used.append("fuel_norm")

        for event in out.events:
            vehicle_id = event.vehicle.get("id") or ""
            rules.compute(event, rules.select_norm(event, norms.get(vehicle_id, [])), to_float)
            out.flags_by_event[event.record_id] = rules.evaluate_event(event, lang)

        # TAKRORLANISHNI OLDINI OLISH: bitta reys ham `waybill` ga, ham
        # `fuel_record` ga tushishi mumkin. Ikkalasini alohida sanash sarf
        # yig'indisini ikki baravar qilib yuborardi va soxta limit buzilishi
        # chiqardi. Yozuvlar o'chirilmaydi — faqat litri bir marta sanaladi.
        out.duplicate_groups = rules.assign_groups(out.events)
        if out.duplicate_groups:
            out.notes.append(
                t(lang, "note.duplicates", count=out.duplicate_groups)
            )
            _attach_source_mismatch(out, lang)

        without_norm = sum(1 for e in out.events if not e.expected_liters)
        if without_norm:
            out.notes.append(
                t(lang, "note.without_norm", count=without_norm)
            )

    if out.counts.get("fuel_limit"):
        out.limits = queries.fetch_limits()
        out.sources_used.append("fuel_limit")

    empty = [n for n in ("fuel_record", "waybill", "fuel_norm", "fuel_limit")
             if not out.counts.get(n)]
    if empty:
        out.notes.append(
            t(lang, "note.empty_tables", tables=", ".join(empty))
        )
    return out


def _attach_source_mismatch(
    collected: Collected, lang: str = texts.DEFAULT_LANG
) -> None:
    """Bir voqeani ikki jadval turlicha yozgan bo'lsa — belgi qo'shadi.

    Belgi guruhning YIG'INDIGA KIRADIGAN yozuviga qo'shiladi, ya'ni hisobotda
    bir marta chiqadi.
    """
    groups: dict[str, list[rules.FuelEvent]] = {}
    for event in collected.events:
        groups.setdefault(event.group_key, []).append(event)
    for members in groups.values():
        if len(members) < 2:
            continue
        flag = rules.source_mismatch_flag(members, lang)
        if not flag:
            continue
        owner = next((e for e in members if e.counts_consumption), members[0])
        collected.flags_by_event.setdefault(owner.record_id, []).append(flag)


# ------------------------------------------------------------- Limit tekshiruvi


def _bucket_label(occurred: Any, window_type: str) -> str | None:
    """Sarf qaysi kun yoki oyga tegishli ekanini nomlaydi."""
    if not isinstance(occurred, datetime):
        return None
    return occurred.strftime("%Y-%m-%d") if window_type == "DAY" else occurred.strftime("%Y-%m")


def _check_limits(
    collected: Collected, lang: str = texts.DEFAULT_LANG
) -> list[dict[str, Any]]:
    """Har bir limit bo'yicha davrdagi sarfni yig'ib, oshganini topadi.

    Yig'indi SQL da emas, shu yerda hisoblanadi: sarf ikki manbadan
    (`fuel_record` va `waybill`) kelishi mumkin va manbalardan biri bo'sh
    bo'lganda SQL varianti ishlamay qolardi.

    DIQQAT: davr chekkasidagi oy to'liq bo'lmasligi mumkin. Masalan 15-avgustdan
    boshlab so'ralsa, avgust oyining faqat yarmi hisobga kiradi va oylik limit
    oshmagandek ko'rinadi. Shuning uchun har bir topilmada nechta yozuv
    qatnashgani (`record_count`) va davr nomi ko'rsatiladi.
    """
    if not collected.limits or not collected.events:
        return []

    usage: dict[tuple[str, str], dict[str, Any]] = {}
    for limit_row in collected.limits:
        subject_type = limit_row.get("subject_type")
        subject_id = limit_row.get("subject_id")
        window_type = limit_row.get("window_type") or "MONTH"
        limit_fuel = limit_row.get("fuel_type")

        for event in collected.events:
            owner = (
                event.driver.get("id") if subject_type == "DRIVER" else event.vehicle.get("id")
            )
            if not owner or owner != subject_id:
                continue
            # Limit muayyan yoqilg'i turiga qo'yilgan bo'lsa, boshqa turdagi
            # sarf unga kirmaydi. Yo'l varaqasida yoqilg'i turi yo'q, shuning
            # uchun u faqat turi ko'rsatilmagan limitga tushadi.
            if limit_fuel and not rules.fuel_matches_policy(limit_fuel, event.fuel_type):
                continue
            if event.consumed is None or event.consumed <= 0:
                continue
            # Takror yozuv litri qayta sanalmaydi (`assign_groups`).
            if not event.counts_consumption:
                continue
            label = _bucket_label(event.occurred_at, window_type)
            if label is None:
                continue

            entry = usage.setdefault(
                (limit_row["limit_id"], label),
                {"limit": limit_row, "liters": 0.0, "records": 0, "documents": []},
            )
            entry["liters"] += event.consumed
            entry["records"] += 1
            if event.document_number:
                entry["documents"].append(event.document_number)

    anomalies: list[dict[str, Any]] = []
    for (limit_id, label), entry in usage.items():
        limit_row = entry["limit"]
        max_liters = to_float(limit_row.get("max_liters")) or 0.0
        if entry["liters"] <= max_liters:
            continue
        flag = rules.limit_flag(
            limit_row=limit_row,
            used_liters=entry["liters"],
            bucket_label=label,
            record_count=entry["records"],
            to_float=to_float,
            lang=lang,
        )
        is_driver = limit_row.get("subject_type") == "DRIVER"
        anomalies.append(
            _anomaly(
                source="fuel_limit",
                record_id=f"{limit_id}@{label}",
                flags=[flag],
                vehicle={} if is_driver else {
                    "id": limit_row.get("subject_id"),
                    "plate_number": limit_row.get("plate_number"),
                    "brand": limit_row.get("brand"),
                    "model": limit_row.get("model"),
                    "transport_type": texts.transport_name(
                        limit_row.get("transport_type"), lang),
                },
                driver={
                    "id": limit_row.get("subject_id"),
                    "full_name": limit_row.get("driver_name"),
                    "table_number": limit_row.get("driver_table_number"),
                } if is_driver else {},
                metrics={"consumed_liters": round(entry["liters"], 3)},
                over_limit=entry["liters"] - max_liters,
                lang=lang,
            )
        )
    return anomalies


# ------------------------------------------------------------------- Reyting


@dataclass
class _Bucket:
    """Bitta mashina yoki haydovchi bo'yicha yig'ilayotgan raqamlar."""

    subject: dict[str, Any]
    records: int = 0
    finding_records: int = 0
    checked_against_norm: int = 0
    consumed_liters: float = 0.0
    distance_km: float = 0.0
    engine_hours: float = 0.0
    consumption_records: int = 0
    known_consumption_records: int = 0
    known_distance_records: int = 0
    known_engine_hour_records: int = 0
    matched_distance_records: int = 0
    fuel_types: set[str] = field(default_factory=set)
    excess_liters: float = 0.0
    unaccounted_liters: float = 0.0
    over_limit_liters: float = 0.0
    flags: dict[str, int] = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)


def _add_event(bucket: _Bucket, event: rules.FuelEvent, flags: list[dict[str, Any]]) -> None:
    bucket.records += 1
    def known(value):
        return value is not None and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    if event.counts_consumption:
        # Keep every denominator on the same deduplicated document grain as
        # consumption. Unknown measurements never enter totals as zero.
        bucket.consumption_records += 1
        fuel = rules.canonical_fuel(event.fuel_type)
        if fuel:
            bucket.fuel_types.add(fuel)
        consumed_known = known(event.consumed) and bool(fuel) and 'FUEL_UNIT_UNVERIFIED' not in event.data_issues
        distance_known = known(event.distance_km)
        if consumed_known:
            bucket.known_consumption_records += 1
            bucket.consumed_liters += event.consumed
        if distance_known:
            bucket.known_distance_records += 1
            bucket.distance_km += event.distance_km
        if known(event.engine_hours):
            bucket.known_engine_hour_records += 1
            bucket.engine_hours += event.engine_hours
        distance_mode = (str(event.calculation_mode or '').strip().upper() in ('KM', 'KM_ONLY', 'DISTANCE')
                         if event.source == 'waybill' else
                         event.basis in ('distance', 'waybill_norm') or
                         (event.basis is None and event.engine_hours in (None, 0)))
        if (consumed_known and distance_known and event.distance_km > 0 and distance_mode
                and not any(f['kind'] in ('IMPOSSIBLE', 'MISMATCH') for f in flags)):
            bucket.matched_distance_records += 1
    if event.expected_liters:
        bucket.checked_against_norm += 1
    if event.excess_liters and event.excess_liters > 0:
        bucket.excess_liters += event.excess_liters

    bucket.unaccounted_liters += rules.unaccounted_liters(flags)
    if rules.has_finding(flags):
        bucket.finding_records += 1
        if event.document_number:
            bucket.documents.append(event.document_number)
    for flag in flags:
        bucket.flags[flag["code"]] = bucket.flags.get(flag["code"], 0) + 1


def _add_limit(bucket: _Bucket, anomaly: dict[str, Any]) -> None:
    """Limitdan oshish reytingga alohida ustun bo'lib tushadi.

    `records` oshirilmaydi: limit topilmasi bitta reys emas, butun davr.
    """
    bucket.finding_records += 1
    bucket.over_limit_liters += anomaly["over_limit_liters"]
    for flag in anomaly["flags"]:
        bucket.flags[flag["code"]] = bucket.flags.get(flag["code"], 0) + 1


def _rows_from(buckets: dict[str, _Bucket], subject_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        rate_complete = (bucket.consumption_records > 0
                         and bucket.matched_distance_records == bucket.consumption_records
                         and len(bucket.fuel_types) == 1)
        rows.append({
            "rank": 0,
            subject_key: bucket.subject,
            "records": bucket.records,
            "finding_records": bucket.finding_records,
            "checked_against_norm": bucket.checked_against_norm,
            "total_consumed_liters": round(bucket.consumed_liters, 3) if bucket.known_consumption_records else None,
            "total_distance_km": round(bucket.distance_km, 3) if bucket.known_distance_records else None,
            "total_engine_hours": round(bucket.engine_hours, 3) if bucket.known_engine_hour_records else None,
            "avg_per100km": (
                round(bucket.consumed_liters / bucket.distance_km * 100, 2)
                if rate_complete and bucket.distance_km > 0 else None
            ),
            "aggregation_coverage": {
                "deduplicated_records": bucket.consumption_records,
                "known_consumption_records": bucket.known_consumption_records,
                "known_distance_records": bucket.known_distance_records,
                "known_engine_hour_records": bucket.known_engine_hour_records,
                "matched_distance_records": bucket.matched_distance_records,
                "consumption_complete": bool(bucket.consumption_records) and bucket.known_consumption_records == bucket.consumption_records,
                "distance_complete": bool(bucket.consumption_records) and bucket.known_distance_records == bucket.consumption_records,
                "rate_complete": rate_complete,
            },
            "unaccounted_liters": round(bucket.unaccounted_liters, 3),
            "over_limit_liters": round(bucket.over_limit_liters, 3),
            "excess_liters": round(bucket.excess_liters, 3),
            "flags": dict(sorted(bucket.flags.items(), key=lambda kv: -kv[1])),
            "documents": bucket.documents[:20],
        })

    rows.sort(key=lambda r: (-r["unaccounted_liters"], -r["over_limit_liters"],
                             -r["excess_liters"], -r["finding_records"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


# --------------------------------------------------------------------- Hisobot


def report(
    *,
    date_from: str,
    date_to: str,
    row_limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> dict[str, Any]:
    """Berilgan sana oralig'i bo'yicha yagona hisobot.

    Faqat ma'lumot yetishmasligi belgilangan yozuv (`DATA_GAP`) `anomalies`
    ro'yxatiga chiqmaydi — u topilma emas. Lekin bunday yozuvlar soni
    `data_quality.notes` da va reytingdagi `checked_against_norm` da ko'rinadi,
    ya'ni jimgina yo'qolmaydi.
    """
    started = time.perf_counter()
    limit = min(row_limit or config.MAX_ROWS, config.MAX_ROWS)

    collected = _collect(date_from, date_to, limit, lang)
    limit_anomalies = _check_limits(collected, lang)

    anomalies: list[dict[str, Any]] = []
    vehicles: dict[str, _Bucket] = {}
    drivers: dict[str, _Bucket] = {}

    for event in collected.events:
        flags = collected.flags_by_event.get(event.record_id) or []

        vehicle_id = event.vehicle.get("id")
        if vehicle_id:
            _add_event(vehicles.setdefault(vehicle_id, _Bucket(subject=event.vehicle)),
                       event, flags)
        driver_id = event.driver.get("id")
        if driver_id:
            _add_event(drivers.setdefault(driver_id, _Bucket(subject=event.driver)),
                       event, flags)

        if not rules.has_finding(flags):
            continue
        anomalies.append(
            _anomaly(
                source=event.source,
                record_id=event.record_id,
                flags=flags,
                vehicle=event.vehicle,
                driver=event.driver,
                occurred_at=event.occurred_at,
                document_number=event.document_number,
                metrics=event.metrics(),
                unaccounted=rules.unaccounted_liters(flags),
                excess=max(event.excess_liters or 0.0, 0.0)
                if any(f["code"] == "CONSUMPTION_OVER_NORM" for f in flags) else 0.0,
                lang=lang,
            )
        )

    for anomaly in limit_anomalies:
        subject = anomaly["driver"] or anomaly["vehicle"]
        subject_id = subject.get("id")
        if subject_id:
            target = drivers if anomaly["driver"] else vehicles
            _add_limit(target.setdefault(subject_id, _Bucket(subject=subject)), anomaly)
    anomalies += limit_anomalies
    anomalies.sort(key=_anomaly_sort_key)

    vehicle_rows = _rows_from(vehicles, "vehicle")
    driver_rows = _rows_from(drivers, "driver")

    # Faqat HAQIQIY topilmalar. Bo'shliqlar bu yerga kirmaydi, chunki ular
    # quyidagi `data_gap_counts` da to'liq sanaladi — aks holda bitta kod
    # bitta javobda ikki xil raqam bilan chiqardi (masalan
    # `FUEL_ISSUED_UNKNOWN` topilmali yozuvlarda 4, hammasida 93) va qaysi
    # biri to'g'riligi noaniq bo'lardi.
    flag_counts: dict[str, int] = {}
    for anomaly in anomalies:
        for flag in anomaly["flags"]:
            if flag["kind"] == rules.KIND_DATA_GAP:
                continue
            flag_counts[flag["code"]] = flag_counts.get(flag["code"], 0) + 1

    # Bo'shliqlar BARCHA tekshirilgan yozuvlar bo'yicha sanaladi, `anomalies`
    # bo'yicha emas.
    #
    # NIMA UCHUN ALOHIDA: faqat bo'shliq belgisi bo'lgan yozuv `anomalies` ga
    # kirmaydi (yuqoridagi `has_finding` filtri) — bu to'g'ri, bo'shliq
    # topilma emas. Ammo shu sababli u hisobotdan butunlay yo'qolib ketardi:
    # nazoratchi "4 ta topilma, 0 litr" ni ko'rib hammasi joyida deb o'ylardi,
    # holbuki 93 hujjatning 93 tasida ham balansni tekshirib bo'lmagan.
    #
    # Ya'ni hisobot bir vaqtda ikkalasini ham ayta olishi kerak:
    # "muammo topilmadi" VA "lekin buni tekshirib ham bo'lmadi".
    #
    # Ma'lumot to'ldirilgan sayin bu raqamlar o'zi kamayadi, shuning uchun
    # ular ayni paytda bazaning to'lganini o'lchaydi.
    data_gap_counts: dict[str, int] = {}
    for event in collected.events:
        for flag in collected.flags_by_event.get(event.record_id) or []:
            if flag["kind"] == rules.KIND_DATA_GAP:
                data_gap_counts[flag["code"]] = data_gap_counts.get(flag["code"], 0) + 1

    result = {
        "generated_at": datetime.now(timezone.utc),
        "period": {"date_from": date_from, "date_to": date_to},
        "summary": {
            "checked_records": len(collected.events),
            "checked_against_norm": sum(1 for e in collected.events if e.expected_liters),
            # Norma qaysi manbadan olingani ALOHIDA ko'rsatiladi: `fuel_norm`
            # oldindan belgilangan norma, `waybill` esa mexanikning o'zi
            # yozgan son. Ikkalasi bir xil ishonchda emas.
            "norm_sources": _norm_sources(collected.events),
            "duplicate_groups": collected.duplicate_groups,
            "finding_records": len(anomalies),
            "vehicles": len(vehicle_rows),
            "drivers": len(driver_rows),
            "vehicles_with_finding": sum(1 for r in vehicle_rows if r["finding_records"]),
            "overconsuming_vehicles": sum(
                1 for r in vehicle_rows
                if r["over_limit_liters"] > 0 or "CONSUMPTION_OVER_NORM" in r["flags"]
            ),
            "drivers_with_finding": sum(1 for r in driver_rows if r["finding_records"]),
            "total_unaccounted_liters": round(
                sum(r["unaccounted_liters"] for r in vehicle_rows), 3),
            "total_over_limit_liters": round(
                sum(r["over_limit_liters"] for r in vehicle_rows)
                + sum(r["over_limit_liters"] for r in driver_rows), 3),
            "total_excess_liters": round(sum(r["excess_liters"] for r in vehicle_rows), 3),
            "flag_counts": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])),
            "data_gap_counts": dict(sorted(data_gap_counts.items(), key=lambda kv: -kv[1])),
        },
        "vehicles": vehicle_rows,
        "drivers": driver_rows,
        "anomalies": anomalies,
        "data_quality": {
            "row_counts": collected.counts,
            "sources_used": sorted(set(collected.sources_used)),
            "notes": collected.notes,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }

    # Bo'sh o'rin: tahlilni `explain.analyze` LLM bilan to'ldiradi.
    # Shablon matni YOZILMAYDI — LLM javob bermasa endpoint 503 qaytaradi.
    result["analysis"] = {"text": "", "anomalies_considered": 0}
    return result


def _norm_sources(events: list[rules.FuelEvent]) -> dict[str, int]:
    """Norma qaysi jadvaldan olingani bo'yicha yozuvlar soni."""
    out: dict[str, int] = {}
    for event in events:
        if not event.expected_liters:
            continue
        key = event.norm_source or "unknown"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":  # pragma: no cover
    # Serversiz tez tekshirish:
    #   python -m oil_detection.detector 2026-08-01 2026-08-31
    import json
    import sys

    if len(sys.argv) != 3:
        print("Foydalanish: python -m oil_detection.detector <boshi> <oxiri>")
        print("Masalan:     python -m oil_detection.detector 2026-08-01 2026-08-31")
        raise SystemExit(2)
    print(json.dumps(report(date_from=sys.argv[1], date_to=sys.argv[2]),
                     ensure_ascii=False, indent=2, default=str))
