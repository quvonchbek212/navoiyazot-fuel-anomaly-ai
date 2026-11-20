"""Javob sxemasi — Swagger shu modellardan chiziladi.

Javob ATAYLAB qat'iy tiplangan: hisobotni keyin dashboard, Telegram bot yoki
ERP o'qiydi. Kalitlar nomi o'zgarib ketmasligi uchun ular Pydantic modelida
qulflangan.

DIQQAT: javobda "daraja" (WARNING/CRITICAL) yo'q. Bunday shkalani bazadagi
hech narsa belgilamaydi, shuning uchun uni o'ylab topish o'rniga belgi TURI
(`kind`) va O'LCHANGAN LITR beriladi — ular ob'ektiv.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["IMPOSSIBLE", "MISMATCH", "OVER_NORM", "OVER_LIMIT", "DATA_GAP"]


class VehicleRef(BaseModel):
    id: str | None = None
    plate_number: str | None = Field(None, examples=["85896SAA"])
    brand: str | None = Field(None, examples=["Labo"])
    model: str | None = None
    transport_type: str | None = None


class DriverRef(BaseModel):
    id: str | None = None
    full_name: str | None = Field(None, examples=["Aliyev Vali Salimovich"])
    table_number: str | None = None


class Period(BaseModel):
    date_from: str
    date_to: str


class DataQuality(BaseModel):
    """Qaysi manbada ma'lumot bor — bo'sh natijani tushuntirish uchun.

    Bu maydon SHART: manba jadval bo'sh bo'lsa javob "anomaliya yo'q" bo'lib
    ko'rinadi. Aslida "tekshirishga ma'lumot yo'q".
    """

    row_counts: dict[str, int] = Field(default_factory=dict)
    sources_used: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------- Reyting


class RankingRow(BaseModel):
    """Bitta mashina yoki haydovchi bo'yicha davr yakuni."""

    rank: int = Field(..., description="1 — eng ko'p litr yo'qolgani")
    records: int = Field(..., description="Davrdagi yozuvlar (reyslar) soni")
    finding_records: int = Field(..., description="Shundan nechtasida topilma bor")
    checked_against_norm: int = Field(
        ..., description="Nechtasi normaga solishtirildi (`fuel_norm` bo'lgani)")
    total_consumed_liters: float | None = Field(None, description="Ma’lum sarflar yig‘indisi; qamrov aggregation_coverage da, hammasi noma’lum bo‘lsa null")
    total_distance_km: float | None = Field(None, description="Ma’lum masofalar yig‘indisi; hammasi noma’lum bo‘lsa null")
    total_engine_hours: float | None = Field(
        None, description="Kran/ekskavator kabi texnika uchun")
    avg_per100km: float | None = None
    aggregation_coverage: dict[str, int | bool] = Field(default_factory=dict,
        description="Bir xil, takrorlanmagan hujjatlar bo‘yicha sarf va masofa qamrovi; qisman yig‘indi to‘liq davr emas")

    unaccounted_liters: float = Field(
        ...,
        description="HISOBDAN TASHQARI litr: balans farqi, hujjatsiz quyish. "
                    "Reyting shu bo'yicha saralanadi.",
    )
    over_limit_liters: float = Field(
        ..., description="`fuel_limit` dan oshgan litr")
    excess_liters: float = Field(
        ..., description="`fuel_norm` dan (tolerans hisobga olingan holda) ortiqcha litr")

    flags: dict[str, int] = Field(
        default_factory=dict, description="Qaysi belgi necha marta uchradi")
    documents: list[str] = Field(
        default_factory=list, description="Topilmali hujjat raqamlari (20 tagacha)")


class VehicleRanking(RankingRow):
    vehicle: VehicleRef = Field(default_factory=VehicleRef)


class DriverRanking(RankingRow):
    driver: DriverRef = Field(default_factory=DriverRef)


# ------------------------------------------------------- Hujjat darajasi


class Flag(BaseModel):
    """Bitta aniqlangan topilma."""

    code: str = Field(..., examples=["BALANCE_MISMATCH"])
    kind: Kind = Field(
        ...,
        description="IMPOSSIBLE — mumkin emas; MISMATCH — ikki manba zid; "
                    "OVER_NORM — normadan oshgan; OVER_LIMIT — limitdan oshgan; "
                    "DATA_GAP — tekshirib bo'lmadi",
    )
    title: str = Field(..., description="O'zbekcha sarlavha")
    detail: str = Field(..., description="Nima uchun belgilangani — raqamlari bilan")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Hisobda ishlatilgan xom qiymatlar — qo'lda tekshirib ko'rish uchun",
    )


class Metrics(BaseModel):
    """Hisoblangan ko'rsatkichlar. Ma'lumot yetishmasa `null`."""

    basis: str | None = Field(
        None,
        description="Sarf qaysi asosda o'lchandi: expected / distance / engine_hour / waybill_norm")
    distance_km: float | None = None
    engine_hours: float | None = None
    consumed_liters: float | None = None
    balance_consumed_liters: float | None = Field(
        None, description="Chiqishdagi bak + quyilgan - qaytgan bak")
    reported_consumed_liters: float | None = Field(
        None, description="Hujjatda yozilgan sarf")
    expected_liters: float | None = Field(
        None, description="Normaga ko'ra kutilgan sarf")
    tolerance_percent: float | None = Field(
        None, description="`fuel_norm.tolerance_percent`")
    allowed_liters: float | None = Field(
        None, description="Kutilgan sarf + tolerans — shundan oshgani anomaliya")
    actual_per100km: float | None = None
    norm_per100km: float | None = None
    actual_per_engine_hour: float | None = None
    norm_per_engine_hour: float | None = None
    deviation_percent: float | None = None
    excess_liters: float | None = None


class Anomaly(BaseModel):
    id: str = Field(..., examples=["waybill:3f6c1b2e-..."])
    source: str = Field(
        ..., description="waybill / fuel_record / fuel_limit", examples=["waybill"])
    document_number: str | None = None
    occurred_at: datetime | None = None
    kinds: list[Kind] = Field(
        default_factory=list, description="Yozuvda qanday turdagi topilmalar bor")
    unaccounted_liters: float = 0.0
    over_limit_liters: float = 0.0
    excess_liters: float = 0.0
    vehicle: VehicleRef = Field(default_factory=VehicleRef)
    driver: DriverRef = Field(default_factory=DriverRef)
    metrics: Metrics = Field(default_factory=Metrics)
    flags: list[Flag] = Field(default_factory=list)
    explanation: str = Field(..., description="O'zbekcha qisqa xulosa")
    explanation_source: Literal["template", "llm"] = Field(
        "template",
        description="Har-yozuv izohini shablon yozadi (LLM'siz), shuning uchun "
                    "bu maydon doim `template`. LLM butun hisobot bo'yicha "
                    "`analysis` da ishlaydi.")


class Summary(BaseModel):
    checked_records: int = 0
    checked_against_norm: int = Field(
        0, description="Nechta yozuv normaga solishtirildi")
    norm_sources: dict[str, int] = Field(
        default_factory=dict,
        description="Norma qaysi manbadan olingani: `fuel_norm` — oldindan "
                    "belgilangan norma, `waybill` — mexanikning o'zi yozgan son",
    )
    duplicate_groups: int = Field(
        0,
        description="Nechta voqea ikkala jadvalda ham yozilgan — sarf litri "
                    "yig'indiga bir marta qo'shilgan",
    )
    finding_records: int = 0
    vehicles: int = 0
    drivers: int = 0
    vehicles_with_finding: int = 0
    overconsuming_vehicles: int = Field(
        0, description="Norma yoki limitdan ortiqcha sarflagan mashinalar soni")
    drivers_with_finding: int = 0
    total_unaccounted_liters: float = 0.0
    total_over_limit_liters: float = 0.0
    total_excess_liters: float = 0.0
    flag_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Haqiqiy topilmalar — nima NOTO'G'RI. Bo'shliq (`DATA_GAP`) "
                    "belgilari bu yerga KIRMAYDI, ular `data_gap_counts` da.",
    )
    data_gap_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Nima TEKSHIRILMAGAN — qaysi ustun bo'sh. BARCHA tekshirilgan "
                    "yozuvlar bo'yicha, `anomalies` bilan cheklanmaydi. "
                    "Bu maydon SHART: bo'shliq topilma emas, shuning uchun "
                    "bo'shliqli yozuv `anomalies` ga kirmaydi va usiz hisobotdan "
                    "butunlay yo'qolib ketardi — \"topilma yo'q\" \"muammo yo'q\" "
                    "bo'lib ko'rinardi. Ma'lumot to'ldirilgan sayin bu raqamlar "
                    "kamayadi.",
    )


class Analysis(BaseModel):
    """Butun hisobot bo'yicha umumiy tahlil — BITTA LLM chaqiruvi.

    Har bir anomaliyaning `explanation` maydoni shablon bilan yoziladi va
    o'z belgilarini to'liq aytadi. LLM shu yerda, chunki uning qo'shadigan
    qiymati bitta yozuvni qayta aytishda emas, yozuvlar ORASIDAGI
    bog'lanishni va bo'shliqlarning ma'nosini ko'rsatishda.

    MATN FAQAT LLM DAN. Shablon bilan to'ldirilmaydi: LLM javob bermasa
    endpoint 503 qaytaradi va frontend "keyinroq urinib ko'ring" deydi.
    Har bir anomaliyaning O'Z `explanation` i esa shablon bilan yoziladi va
    LLM ga bog'liq emas.
    """

    text: str = Field("", description="O'zbekcha tahlil")
    anomalies_considered: int = Field(
        0, description="Tahlilga nechta yuqori anomaliya kiritildi")


class FuelReport(BaseModel):
    generated_at: datetime
    period: Period
    summary: Summary
    analysis: Analysis = Field(
        default_factory=Analysis,
        description="Umumiy tahlil: manzara, takrorlanadigan naqsh, bo'shliqlar, tavsiya",
    )
    vehicles: list[VehicleRanking] = Field(
        default_factory=list, description="Mashinalar — eng ko'p litr yo'qolgani birinchi")
    drivers: list[DriverRanking] = Field(
        default_factory=list, description="Haydovchilar — eng ko'p litr yo'qolgani birinchi")
    anomalies: list[Anomaly] = Field(
        default_factory=list, description="Hujjat darajasidagi tafsilot")
    data_quality: DataQuality
    elapsed_seconds: float = 0.0
