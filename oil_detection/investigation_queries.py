"""Allowlisted SELECT tools. The LLM cannot supply SQL, IDs or date filters.

One query per cursor, explicitly READ ONLY even if the shared configuration
has read-only disabled. Query limits are resource limits, not fuel thresholds.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from oil_detection.queries import OilDataError, read_only_cursor
from db.sql_guard import ensure_read_only

ROW_LIMIT = 30
TASK_LIMIT = 20
LEDGER_LIMIT = 100


def select(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    # Validate before opening a connection, including on developer mistakes.
    safe_sql = ensure_read_only(sql)
    try:
        with read_only_cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '10000'")
            cur.execute("SET LOCAL timezone = 'Asia/Tashkent'")
            cur.execute(safe_sql, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        # Do not expose connection strings or SQL/server errors to the model.
        raise OilDataError("Investigation evidence query unavailable") from exc


# No names, comments, raw payloads or credentials are sent to the model.
WAYBILL_SELECT = """
select w.id::text as id, w.waybill_number, w.issue_date, w.status,
       w.vehicle_id::text, w.driver_id::text, w.trip_id::text,
       w.route_id::text, w.transport_request_id::text, w.branch_id::text,
       w.trailer_id::text, w.fuel_type, w.calculation_mode, w.work_mode,
       w.actual_departure_at, w.actual_return_at,
       w.fuel_at_departure_liters, w.fuel_issued_liters,
       w.fuel_at_return_liters, w.fuel_consumed_liters, w.fuel_norm_liters,
       w.odometer_start_km, w.odometer_end_km, w.motohours_worked,
       w.cargo_weight_tons, w.passenger_count, w.outbound_tons, w.inbound_tons,
       w.outbound_km, w.inbound_km, w.cargo_ton_km,
       v.plate_number, v.brand, v.model, v.transport_type, v.engine_power,
       coalesce(tasks.rows, '[]'::jsonb) as tasks,
       coalesce(tasks.total, 0) as task_count
from waybill w
left join transport_vehicle v on v.id=w.vehicle_id
left join lateral (
    select jsonb_agg(to_jsonb(t) - 'total') as rows, max(total) as total
    from (
        select sequence_number, cargo_weight_tons, distance_km, trip_count,
               loading_location, unloading_location, measurement_basis,
               count(*) over () as total
        from waybill_task where waybill_id=w.id
        order by sequence_number limit 20
    ) t
) tasks on true
"""


class Repository:
    def target(self, waybill_id: str) -> dict[str, Any] | None:
        rows = select(WAYBILL_SELECT + " where w.id=%s::uuid", (waybill_id,))
        return rows[0] if rows else None

    def candidates(self, target: dict, days: int, mode: str) -> list[dict]:
        filters = {
            "peer_trips": "w.vehicle_id <> %s::uuid and (w.transport_request_id=%s::uuid or w.route_id=%s::uuid) and lower(trim(v.brand))=lower(trim(%s)) and lower(trim(v.model))=lower(trim(%s))",
            "vehicle_history": "w.vehicle_id=%s::uuid",
            "driver_history": "w.driver_id=%s::uuid",
        }
        # A missing route/model is not permission to compare the entire fleet.
        if mode == "peer_trips":
            if not all(target.get(k) for k in ("vehicle_id", "brand", "model")) or not (
                target.get("route_id") or target.get("transport_request_id")
            ):
                return []
            scope = (target["vehicle_id"], target.get("transport_request_id"),
                     target.get("route_id"), target["brand"], target["model"])
        else:
            key = "vehicle_id" if mode == "vehicle_history" else "driver_id"
            if not target.get(key):
                return []
            scope = (target[key],)
        on = target["issue_date"]
        if isinstance(on, str):
            on = date.fromisoformat(on)
        return select(WAYBILL_SELECT + """
            where w.id<>%s::uuid and w.branch_id is not distinct from %s::uuid
              and w.status in ('CLOSED','RETURNED')
              and w.issue_date between %s and %s
              and """ + filters[mode] + """
            order by (w.transport_request_id=%s::uuid) desc nulls last,
                     w.issue_date desc, w.id limit %s
            """, (target["id"], target.get("branch_id"), on - timedelta(days=days), on,
                  *scope, target.get("transport_request_id"), ROW_LIMIT + 1))

    def fuelings(self, target: dict) -> list[dict]:
        return select("""
            select f.fueling_id::text, f.occurred_at, f.quantity, f.fuel_type,
                   f.warehouse_id::text, f.external_station,
                   case when r.latitude between -90 and 90 and r.longitude between -180 and 180
                        then r.latitude end as station_latitude,
                   case when r.latitude between -90 and 90 and r.longitude between -180 and 180
                        then r.longitude end as station_longitude
            from waybill_fueling f
            left join reference_data r on r.id=f.warehouse_id and r.active
              and r.catalog_type='FUEL_WAREHOUSES' and f.external_station is not true
            where f.waybill_id=%s::uuid
            order by f.occurred_at, f.fueling_id limit %s
        """, (target["id"], LEDGER_LIMIT + 1))

    def gps_analysis(self, target: dict, *, deadline=None) -> dict:
        """Join read-only document evidence with one bounded ATIL GPS window."""
        from oil_detection.gps_analysis import analyze_waybill

        start, end = target.get("actual_departure_at"), target.get("actual_return_at")
        valid = all(isinstance(v, datetime) and v.utcoffset() is not None for v in (start, end))
        fuelings = norms = None
        unavailable = []
        if valid and start < end:
            try:
                fuelings = self.fuelings(target)
            except OilDataError:
                unavailable.append("FUELING_SOURCE_UNAVAILABLE")
            try:
                norms = self.gps_norms(target)
            except OilDataError:
                unavailable.append("NORM_SOURCE_UNAVAILABLE")
        result = analyze_waybill(target, fuelings=fuelings, norms=norms, deadline=deadline)
        result.setdefault("limitations", []).extend(unavailable)
        if unavailable and result.get("status") == "COMPLETE":
            result["status"] = "PARTIAL"
        return result

    def fuel_records(self, target: dict) -> list[dict]:
        # They are source records, NOT additional consumption or independent proof.
        return select("""
            select id::text, source_type, occurred_at, liters, fuel_type,
                   trip_id::text, source_reference
            from fuel_record where vehicle_id=%s::uuid
              and (trip_id=%s::uuid or source_reference=%s)
            order by occurred_at, id limit %s
        """, (target.get("vehicle_id"), target.get("trip_id"),
              target.get("waybill_number"), LEDGER_LIMIT + 1))

    def norms(self, target: dict) -> list[dict]:
        return select("""
            select id::text, fuel_type, liters_per100km, liters_per_engine_hour,
                   tolerance_percent, effective_from, effective_to
            from fuel_norm where vehicle_id=%s::uuid
              and effective_from<=%s::date
              and (effective_to is null or effective_to>=%s::date)
            order by effective_from desc, id limit %s
        """, (target.get("vehicle_id"), target["issue_date"], target["issue_date"], ROW_LIMIT + 1))

    def gps_norms(self, target: dict) -> list[dict]:
        """Only policies covering every local date in the actual trip window."""
        from atil_ai_dispetcher.config import TIMEZONE

        first = target["actual_departure_at"].astimezone(TIMEZONE).date()
        last = (target["actual_return_at"]-timedelta(microseconds=1)).astimezone(TIMEZONE).date()
        return select("""
            select id::text, fuel_type, liters_per100km, liters_per_engine_hour,
                   tolerance_percent, effective_from, effective_to
            from fuel_norm where vehicle_id=%s::uuid
              and effective_from<=%s::date
              and (effective_to is null or effective_to>=%s::date)
            order by effective_from desc, id limit %s
        """, (target.get("vehicle_id"), first, last, ROW_LIMIT + 1))

    def repairs(self, target: dict, days: int) -> list[dict]:
        return select("""
            select id::text, status, component_category, opened_at,
                   repaired_at, completed_at, blocks_release
            from vehicle_repair where vehicle_id=%s::uuid
              and opened_at < (%s::date + 1)
              and (coalesce(completed_at, repaired_at) is null
                   or coalesce(completed_at, repaired_at)>=(%s::date - %s::int))
            order by opened_at desc, id limit %s
        """, (target.get("vehicle_id"), target["issue_date"], target["issue_date"], days, ROW_LIMIT + 1))

    def gps(self, target: dict) -> list[dict]:
        # Full trip only: no assumed timezone for a naive timestamp, no issue-date
        # substitution and no fabricated idle time from stationary GPS points.
        return select("""
            select count(*) as points, min(a.fix_time) as first_fix,
                   max(a.fix_time) as last_fix
            from gps_archive_point a
            join vehicle_gps g on g.id=a.binding_id and g.vehicle_id=a.vehicle_id
            where a.vehicle_id=%s::uuid and a.fix_time between %s and %s
              and g.verified_from<=a.fix_time
              and (g.unbound_at is null or a.fix_time<g.unbound_at)
        """, (target.get("vehicle_id"), target.get("actual_departure_at"),
              target.get("actual_return_at")))
