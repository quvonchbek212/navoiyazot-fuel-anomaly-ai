"""Yoqilg'i tekshiruvi sozlamalari.

BU YERDA BIRORTA HAM "MEYOR" YO'Q — bu ataylab shunday.

Nima bilan solishtirish kerakligini BAZA aytadi:
    fuel_norm   -> liters_per100km / liters_per_engine_hour + tolerance_percent
    fuel_limit  -> subject_type (DRIVER|VEHICLE), window_type (DAY|MONTH), max_liters

Qolgan qoidalar arifmetikaning o'zi bo'lgani uchun ularga ham chegara kerak
emas: qaytgan yoqilg'i mavjudidan ko'p bo'lsa — bu qanchaligidan qat'i nazar
mumkin emas; balans tenglamasi bajarilmasa — bajarilmagan.

Quyidagi uch qiymat anomaliya chegarasi EMAS, ular xizmatning o'z ishi:
resurs himoyasi va LLM izohi.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


# --------------------------------------------------------------- Resurs himoyasi
# Bitta so'rovda bazadan o'qiladigan eng ko'p yozuv. Bu anomaliya chegarasi
# emas — bazani va xotirani himoya qiladi.
# MUHIM: chegaraga yetilsa javobning `data_quality.notes` ida ochiq yoziladi,
# ya'ni natija jimgina qirqilib qolmaydi.
MAX_ROWS = _int("OIL_MAX_ROWS", 20000)

# ------------------------------------------------------------------- LLM izohi
# Anomaliyani ARIFMETIKA topadi, LLM esa uni odam tiliga o'giradi.
#
# IZOH DOIM YOZILADI, o'chirgich yo'q. Ilgari `?explain=false` va
# `OIL_LLM_EXPLAIN=false` bilan uni bekor qilish mumkin edi; ikkalasi ham
# olib tashlandi, chunki javob har doim izoh bilan to'liq kelishi kerak.
# NARXI: har bir chaqiruv sekundlar oladi (chatbotda o'lchangan: model
# qayta yuklansa 14-67 s). LLM javob bermasa SHABLONGA TUSHILMAYDI —
# endpoint 503 qaytaradi va frontend "keyinroq urinib ko'ring" deydi.

#: Tahlilga nechta YUQORI anomaliya kiritiladi (hammasi emas).
#: Ro'yxat yo'qolgan litr bo'yicha saralangani uchun birinchilar eng
#: muhimlari. Kattaroq son = uzunroq prompt = sekinroq javob.
LLM_ANALYZE_TOP = _int("OIL_LLM_ANALYZE_TOP", 5)

#: Eski nom — mavjud `.env` fayllar buzilmasin.
LLM_EXPLAIN_LIMIT = LLM_ANALYZE_TOP

# Agent limits govern resource use, never fuel/anomaly thresholds.
AGENT_MAX_ROUNDS = max(1, min(_int("OIL_AGENT_MAX_ROUNDS", 3), 5))
AGENT_LLM_TIMEOUT_SECONDS = max(5, min(_int("OIL_AGENT_LLM_TIMEOUT_SECONDS", 90), 180))
AGENT_FINAL_TIMEOUT_SECONDS = max(5, min(_int("OIL_AGENT_FINAL_TIMEOUT_SECONDS", 180), 300))
AGENT_TOTAL_TIMEOUT_SECONDS = max(10, min(_int("OIL_AGENT_TOTAL_TIMEOUT_SECONDS", 300), 600))
