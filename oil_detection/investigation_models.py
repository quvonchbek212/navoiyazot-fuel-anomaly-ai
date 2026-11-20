"""Contracts for a bounded, evidence-seeking fuel investigation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InvestigationRequest(StrictModel):
    waybill_id: UUID
    lang: Literal["uz", "ru", "en"] = "uz"
    question: str = Field(
        "Yuk, o'xshash qatnovlar va quyish dalillari orqali sarfni tekshir.",
        min_length=1, max_length=1000,
    )
    comparison_days: int = Field(14, ge=1, le=90,
        description="Reys sanasigacha bo'lgan qidiruv oynasi; sarf meyori emas")


ToolName = Literal[
    "fuel_ledger", "norms", "peer_trips", "vehicle_history",
    "driver_history", "gps_coverage", "repairs",
]


class SearchStep(StrictModel):
    tools: list[ToolName] = Field(max_length=3)
    purpose: str = Field(min_length=1, max_length=400,
        description="Qisqa tekshiruv maqsadi; ichki fikrlash jarayoni emas")


class Evidence(BaseModel):
    id: str
    tool: str
    state: Literal["available", "missing", "unavailable"]
    sources: list[str]
    facts: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)
    truncated: bool = False


class CitedStatement(StrictModel):
    text: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class Hypothesis(StrictModel):
    # These are avenues of investigation, never established causal verdicts.
    kind: Literal["work_conditions", "recording", "technical", "unresolved"]
    text: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class InvestigationConclusion(StrictModel):
    status: Literal["needs_review", "insufficient_evidence"]
    summary: CitedStatement
    observations: list[CitedStatement] = Field(min_length=1, max_length=6)
    hypotheses: list[Hypothesis] = Field(max_length=4)
    counterevidence: list[CitedStatement] = Field(max_length=4)
    missing_information: list[CitedStatement] = Field(max_length=5)
    next_actions: list[CitedStatement] = Field(min_length=1, max_length=5)


class InvestigationStep(BaseModel):
    number: int
    purpose: str
    tools: list[str]
    evidence_ids: list[str]


class InvestigationReport(BaseModel):
    investigation_id: UUID
    generated_at: datetime
    waybill_id: UUID
    lang: Literal["uz", "ru", "en"]
    question: str
    comparison_days: int
    conclusion: InvestigationConclusion
    evidence: list[Evidence]
    steps: list[InvestigationStep]
    unvisited_tools: list[str]
    elapsed_seconds: float
    gps_analysis: dict[str, Any] | None = None
