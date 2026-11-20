"""Inspectable evidence, exact arithmetic and conservative peer eligibility.

No learned consumption model, risk score or estimated missing cargo. Rates are
observed document values, not a prediction or a verdict about a driver.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from oil_detection.investigation_models import Evidence
from oil_detection.investigation_queries import Repository, ROW_LIMIT, LEDGER_LIMIT
from oil_detection.rules import canonical_fuel, match_fuel_norms


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def normalized(value: Any) -> str | None:
    return " ".join(str(value).casefold().split()) if value not in (None, "") else None


def _rounded(value: Decimal | None) -> float | None:
    return None if value is None else float(round(value, 3))


def work_profile(row: dict) -> dict:
    """Preserve directional/task grain. Never sum task loads into a tank load."""
    tasks = row.get("tasks") or []
    task_complete = len(tasks) == row.get("task_count", len(tasks))
    legs = [number(row.get(k)) for k in ("outbound_tons", "inbound_tons")]
    weight = number(row.get("cargo_weight_tons"))
    task_weights = [number(t.get("cargo_weight_tons")) for t in tasks]
    issues = []
    values = [v for v in [*legs, weight, *task_weights] if v is not None]
    if any(v < 0 for v in values):
        issues.append("NEGATIVE_CARGO")
    if not task_complete:
        issues.append("TASKS_TRUNCATED")
    passenger_vehicle = row.get("transport_type") in ("PASSENGER_CAR", "BUS", "MINIBUS")
    passengers = number(row.get("passenger_count"))
    if all(v is not None for v in legs):
        chosen, basis = legs, "directional_tons"
    elif weight is not None:
        chosen, basis = [weight], "waybill.cargo_weight_tons"
    elif tasks and task_complete and all(v is not None for v in task_weights):
        chosen, basis = task_weights, "waybill_task.cargo_weight_tons"
    else:
        chosen, basis = [], None
    state = "unknown"
    if chosen:
        state = "mixed" if min(chosen) == 0 < max(chosen) else (
            "loaded" if max(chosen) > 0 else "recorded_empty")
        # Sources may have different grain, so do not compare their sums.
        # Contradictory empty/loaded descriptions still cannot be ignored.
        if (max(chosen) == 0 and any(v > 0 for v in values)) or (
            weight == 0 and max(chosen) > 0):
            issues.append("CARGO_SOURCES_CONFLICT")
    if issues:
        state = "unknown"
    if passenger_vehicle:
        basis = "waybill.passenger_count"
        if passengers is None or passengers < 0:
            state, chosen = "unknown", []
            issues.append("PASSENGER_LOAD_UNKNOWN")
        elif not issues:
            state = "loaded" if passengers > 0 else "recorded_empty"
            chosen = [passengers]
    direction = None
    if tasks and task_complete and all(t.get("loading_location") and t.get("unloading_location") for t in tasks):
        direction = [[normalized(t["loading_location"]), normalized(t["unloading_location"])] for t in tasks]
    # Include per-task weights, counts and distances. One heavy load is not
    # equivalent to many light loads, even when total tonnage happens to match.
    signature = clean({
        "basis": basis, "weights": chosen,
        "header_cargo_weight_tons": weight,
        "tasks": [{k: t.get(k) for k in ("cargo_weight_tons", "trip_count", "distance_km", "measurement_basis")} for t in tasks],
        "outbound_km": row.get("outbound_km"), "inbound_km": row.get("inbound_km"),
        "passenger_count": passengers,
    }) if state != "unknown" else None
    return {"load_state": state, "load_basis": basis, "load_signature": signature,
            "direction": direction, "task_count": row.get("task_count", len(tasks)),
            "issues": issues}


def metrics(row: dict) -> dict:
    start, issued, end, consumed = [number(row.get(k)) for k in (
        "fuel_at_departure_liters", "fuel_issued_liters", "fuel_at_return_liters", "fuel_consumed_liters")]
    before, after = [number(row.get(k)) for k in ("odometer_start_km", "odometer_end_km")]
    distance = after - before if before is not None and after is not None else None
    balance = start + issued - end if all(v is not None for v in (start, issued, end)) else None
    difference = consumed - balance if consumed is not None and balance is not None else None
    issues = []
    if any(v is not None and v < 0 for v in (start, issued, end, consumed, before, after)):
        issues.append("NEGATIVE_VALUE")
    if distance is not None and distance < 0:
        issues.append("ODOMETER_BACKWARDS")
    if difference is not None and difference != 0:
        issues.append("BALANCE_MISMATCH")
    if balance is not None and balance < 0:
        issues.append("RETURN_EXCEEDS_AVAILABLE")
    fuel = canonical_fuel(row.get("fuel_type"))
    unit_unverified = fuel in ("CNG", "LNG", "GAS")
    if unit_unverified:
        issues.append("GAS_QUANTITY_UNIT_UNVERIFIED")
    if not fuel:
        issues.append("FUEL_TYPE_UNKNOWN")
    mode = normalized(row.get("calculation_mode"))
    if mode in ("engine_hour", "engine_hours", "moto_hour", "motohours", "moto_hours",
                "motor_hour", "motor_hours", "motohours_only", "km_and_motohours"):
        issues.append("ENGINE_HOUR_MODE_NO_DISTANCE_RATE")
    elif mode not in ("km", "km_only", "distance"):
        issues.append("CALCULATION_MODE_UNKNOWN")
    closed = row.get("status") in ("CLOSED", "RETURNED")
    rate = consumed / distance * 100 if (
        closed and not issues and consumed is not None and consumed >= 0
        and distance is not None and distance > 0
    ) else None
    return {
        "consumed_liters": _rounded(consumed), "distance_km": _rounded(distance),
        "recorded_per100km": _rounded(rate), "balance_consumed_liters": _rounded(balance),
        "balance_difference_liters": _rounded(difference), "balance_testable": difference is not None,
        "completed": closed, "issues": issues,
        "rate_unit": "L / 100 km" if rate is not None else None,
    }


def context(row: dict) -> dict:
    keep = ("id", "waybill_number", "issue_date", "status", "vehicle_id", "driver_id", "trip_id",
            "route_id", "transport_request_id", "branch_id", "brand", "model", "engine_power",
            "transport_type", "trailer_id", "fuel_type", "calculation_mode", "work_mode",
            "actual_departure_at", "actual_return_at", "motohours_worked", "cargo_weight_tons",
            "outbound_tons", "inbound_tons", "outbound_km", "inbound_km", "cargo_ton_km", "passenger_count",
            "fuel_at_departure_liters", "fuel_issued_liters", "fuel_at_return_liters")
    return clean({**{k: row.get(k) for k in keep}, "work": work_profile(row), "metrics": metrics(row)})


def comparison(target: dict, candidate: dict) -> dict:
    a, b = context(target), context(candidate)
    matched, different, unknown = [], [], []
    for key in ("brand", "model", "engine_power", "transport_type", "route_id",
                "fuel_type", "calculation_mode", "work_mode"):
        if key == "fuel_type":
            x, y = canonical_fuel(a.get(key)) or None, canonical_fuel(b.get(key)) or None
        else:
            x, y = normalized(a.get(key)), normalized(b.get(key))
        (unknown if x is None or y is None else matched if x == y else different).append(key)
    # An absent trailer ID is not evidence of a confirmed no-trailer journey.
    x, y = a.get("trailer_id"), b.get("trailer_id")
    (unknown if x is None or y is None else matched if x == y else different).append("trailer_id")
    for key in ("load_signature", "direction"):
        x, y = a["work"][key], b["work"][key]
        (unknown if x is None or y is None else matched if x == y else different).append(key)
    # Keep the same day requirement explicit instead of silently broadening a
    # comparison over different weather/shift conditions to obtain a baseline.
    (matched if a["issue_date"] == b["issue_date"] else different).append("issue_date")
    for name, row in (("target", a), ("candidate", b)):
        if row["metrics"]["recorded_per100km"] is None:
            unknown.append(name + "_valid_consumption_rate")
    if a["metrics"]["distance_km"] != b["metrics"]["distance_km"]:
        different.append("distance_km")
    for name, row in (("target", a), ("candidate", b)):
        if row["work"]["task_count"] == 0:
            unknown.append(name + "_task_count")
        elif row["work"]["load_signature"] and any(
            t.get("trip_count") is None for t in row["work"]["load_signature"]["tasks"]
        ):
            unknown.append(name + "_trip_count")
    comparable = not different and not unknown
    delta = None
    if comparable:
        delta = _rounded(number(a["metrics"]["recorded_per100km"]) - number(b["metrics"]["recorded_per100km"]))
    return {
        "waybill_id": b["id"], "vehicle_id": b["vehicle_id"], "driver_id": b["driver_id"],
        "issue_date": b["issue_date"], "load_state": b["work"]["load_state"],
        "cargo_weight_tons": b["cargo_weight_tons"], "metrics": b["metrics"],
        "outbound_tons": b["outbound_tons"], "inbound_tons": b["inbound_tons"],
        "passenger_count": b["passenger_count"],
        "work": b["work"], "motohours_worked": b["motohours_worked"],
        "same_transport_request": bool(a["transport_request_id"] and a["transport_request_id"] == b["transport_request_id"]),
        "matched": matched, "different": different, "unknown": unknown,
        "comparable_on_recorded_conditions": comparable,
        "target_minus_candidate_per100km": delta,
    }


class EvidenceTools:
    def __init__(self, repository: Repository, target: dict, days: int, *, gps_deadline=None):
        self.repository, self.target, self.days = repository, target, days
        self.gps_deadline = gps_deadline
        self.gps_analysis = None

    def initial(self) -> Evidence:
        facts = context(self.target)
        limits = ["DOCUMENT_VALUES_ARE_NOT_SENSOR_MEASUREMENTS", "TASK_LOADS_ARE_NOT_SUMMED_AS_TANK_LOAD"]
        if facts["work"]["load_state"] == "unknown":
            limits.append("CARGO_UNKNOWN_OR_CONFLICTING")
        if not facts["work"]["direction"]:
            limits.append("DIRECTION_NOT_VERIFIED")
        if not facts["metrics"]["balance_testable"]:
            limits.append("FUEL_BALANCE_INCOMPLETE")
        if not facts["metrics"]["completed"]:
            limits.append("TRIP_NOT_COMPLETED_NO_FINAL_CONSUMPTION_COMPARISON")
        if "GAS_QUANTITY_UNIT_UNVERIFIED" in facts["metrics"]["issues"]:
            limits.append("LEGACY_LITERS_FIELDS_FOR_GAS_REQUIRE_UNIT_VERIFICATION_NO_CONVERSION")
        limits.extend(code for code in facts["metrics"]["issues"] if code in (
            "FUEL_TYPE_UNKNOWN", "ENGINE_HOUR_MODE_NO_DISTANCE_RATE", "CALCULATION_MODE_UNKNOWN"))
        return Evidence(id="E0", tool="context", state="available", sources=["waybill", "waybill_task", "transport_vehicle"],
                        facts=facts, limitations=limits)

    def run(self, name: str, evidence_id: str) -> Evidence:
        if name in ("peer_trips", "vehicle_history", "driver_history"):
            return self._comparisons(name, evidence_id)
        if name == "fuel_ledger":
            return self._ledger(evidence_id)
        if name == "norms":
            return self._norms(evidence_id)
        if name == "gps_coverage":
            return self._gps(evidence_id)
        if name == "repairs":
            rows = self.repository.repairs(self.target, self.days)
            return Evidence(id=evidence_id, tool=name, state="available" if rows else "missing",
                sources=["vehicle_repair"], facts={"records": clean(rows[:ROW_LIMIT])}, truncated=len(rows)>ROW_LIMIT,
                limitations=["REPAIR_RECORD_IS_NOT_PROOF_OF_FUEL_CAUSE", "CURRENT_REPAIR_STATE_MAY_INCLUDE_LATER_UPDATES"])
        raise ValueError("Unknown evidence tool")

    def _comparisons(self, name: str, eid: str) -> Evidence:
        rows = self.repository.candidates(self.target, self.days, name)
        candidates = [comparison(self.target, row) for row in rows[:ROW_LIMIT]]
        candidates.sort(key=lambda c: (not c["comparable_on_recorded_conditions"], len(c["different"]), len(c["unknown"])))
        comparable = [c for c in candidates if c["comparable_on_recorded_conditions"]]
        blockers = Counter(k for c in candidates for k in c["unknown"] + c["different"])
        return Evidence(id=eid, tool=name, state="available" if candidates else "missing",
            sources=["waybill", "waybill_task", "transport_vehicle"],
            facts={"lookback_days": self.days, "through_issue_date": clean(self.target["issue_date"]),
                   "candidate_count": len(candidates), "comparable_count": len(comparable),
                   "comparison_blockers": dict(blockers), "candidates": candidates},
            truncated=len(rows)>ROW_LIMIT, limitations=[
                "CANDIDATES_ARE_NOT_AUTOMATICALLY_COMPARABLE", "NO_MEASURED_WEATHER_OR_TRAFFIC_ADJUSTMENT",
                "RECORDED_CONDITIONS_DO_NOT_PROVE_CAUSATION", "HISTORY_IS_CONTEXT_NOT_A_PREDICTION",
            ] + (["NO_VERIFIED_COMPARISON"] if not comparable else []))

    def _ledger(self, eid: str) -> Evidence:
        fuelings = self.repository.fuelings(self.target)
        records = self.repository.fuel_records(self.target)
        truncated = len(fuelings)>LEDGER_LIMIT or len(records)>LEDGER_LIMIT
        fuelings, records = fuelings[:LEDGER_LIMIT], records[:LEDGER_LIMIT]
        fuel = canonical_fuel(self.target.get("fuel_type"))
        quantities = [number(r.get("quantity")) for r in fuelings]
        usable = bool(fuelings) and not truncated and bool(fuel) and all(
            canonical_fuel(r.get("fuel_type")) == fuel and q is not None and q >= 0 for r, q in zip(fuelings, quantities))
        total = sum(quantities, Decimal(0)) if usable else None
        issued = number(self.target.get("fuel_issued_liters"))
        difference = issued-total if issued is not None and total is not None else None
        # Exact time/type/quantity matches show potential lineage; never add
        # the two tables or claim they are independent corroboration.
        matched = sum(1 for r in records if any(
            r.get("occurred_at") is not None and r.get("occurred_at") == f.get("occurred_at") and r.get("fuel_type") == f.get("fuel_type")
            and number(r.get("liters")) is not None and number(r.get("liters")) == number(f.get("quantity"))
            for f in fuelings))
        return Evidence(id=eid, tool="fuel_ledger", state="available", sources=["waybill", "waybill_fueling", "fuel_record"],
            truncated=truncated, facts={"balance": metrics(self.target), "fueling_count": len(fuelings),
                "fuelings": clean([{k: f.get(k) for k in ("fueling_id", "occurred_at", "quantity", "fuel_type", "warehouse_id", "external_station")} for f in fuelings]), "source_record_count": len(records),
                "source_records": clean(records), "possible_source_copies": matched,
                "recorded_fueling_total_liters": _rounded(total), "issued_minus_fueling_total_liters": _rounded(difference)},
            limitations=["FUEL_RECORD_LITERS_ARE_NOT_ADDED_TO_CONSUMPTION", "MATCHING_SOURCES_MAY_BE_COPIES",
                         "ABSENT_FUELINGS_DO_NOT_PROVE_ZERO_REFUELING", "FUELING_REGISTER_COMPLETENESS_NOT_VERIFIED"])

    def _norms(self, eid: str) -> Evidence:
        rows = self.repository.norms(self.target)
        selected = match_fuel_norms(rows[:ROW_LIMIT], self.target.get("fuel_type"))
        return Evidence(id=eid, tool="norms", state="available" if rows else "missing", sources=["fuel_norm"],
            facts={"on_issue_date": clean(self.target["issue_date"]), "matching_fuel_norms": clean(selected),
                   "other_fuel_or_unknown_count": len(rows[:ROW_LIMIT])-len(selected)}, truncated=len(rows)>ROW_LIMIT,
            limitations=["DATE_AND_FUEL_TYPE_MUST_MATCH", "DO_NOT_SELECT_ARBITRARILY_BETWEEN_OVERLAPPING_NORMS",
                         "A_NORM_IS_A_POLICY_NOT_PROOF_OF_ACTUAL_CONSUMPTION"])

    def _gps(self, eid: str) -> Evidence:
        analyze = getattr(self.repository, "gps_analysis", None)
        if callable(analyze):
            self.gps_analysis = analyze(self.target, deadline=self.gps_deadline)
            report = self.gps_analysis
            gps = report.get("gps", {})
            facts = {
                "status": report.get("status"), "period": report.get("period"),
                "gps": {k: gps.get(k) for k in ("distance_km", "observed_distance_km", "distance_source",
                    "complete", "points", "signal_gaps", "local_signal_gaps", "api_signal_gaps", "api_history_gap_counts",
                    "observed_stop_minutes", "observed_moving_minutes", "last_signal_at")},
                "comparison": {k: report.get("comparison", {}).get(k) for k in ("document_distance_km",
                    "gps_distance_km", "difference_km", "consumed_liters", "liters_per100km", "norm_per100km",
                    "expected_liters", "excess_liters", "comparable", "reasons")},
                "fueling_observations": [{k: item.get(k) for k in ("occurred_at", "status", "gps_time",
                    "time_difference_seconds", "distance_to_station_meters", "station_coordinates_available")}
                    for item in report.get("fuelings", [])],
            }
            limits = list(report.get("limitations", []))
            limits.extend(["DOCUMENT_FUEL_IS_NOT_A_SENSOR_MEASUREMENT",
                           "STATIONARY_GPS_DOES_NOT_PROVE_ENGINE_RUNNING",
                           "REFUELING_LOCATION_IS_CONTEXT_NOT_PROOF_OF_FUEL_TRANSFER"])
            if not facts["comparison"].get("comparable"):
                limits.append("GPS_FUEL_RATE_NOT_COMPARABLE")
            state = "unavailable" if report.get("status") == "UNAVAILABLE" else (
                "available" if gps.get("points") or gps.get("distance_km") is not None or gps.get("observed_distance_km") is not None else "missing")
            return Evidence(id=eid, tool="gps_coverage", state=state,
                            sources=["ATIL_GPS_API", "waybill", "waybill_fueling", "fuel_norm"],
                            facts=clean(facts), limitations=list(dict.fromkeys(limits)),
                            truncated=bool(gps.get("truncated")))
        start, end = [self.target.get(k) for k in ("actual_departure_at", "actual_return_at")]
        valid = all(isinstance(v, datetime) and v.utcoffset() is not None for v in (start, end))
        if not valid or end <= start:
            return Evidence(id=eid, tool="gps_coverage", state="missing", sources=["waybill"], facts={},
                            limitations=["ACTUAL_TRIP_TIME_WINDOW_UNKNOWN_OR_INVALID"])
        rows = self.repository.gps(self.target)
        facts = rows[0] if rows else {"points": 0}
        return Evidence(id=eid, tool="gps_coverage", state="available" if facts["points"] else "missing",
            sources=["gps_archive_point", "vehicle_gps", "waybill"], facts=clean({**facts, "from_at": start, "to_at": end}),
            limitations=["POINT_COUNT_DOES_NOT_PROVE_CONTINUOUS_COVERAGE", "NO_GPS_DISTANCE_OR_IDLE_TIME_COMPUTED",
                         "NO_ENGINE_OR_FUEL_SENSOR_VALUES_READ", "STATIONARY_GPS_DOES_NOT_PROVE_ENGINE_RUNNING"])
