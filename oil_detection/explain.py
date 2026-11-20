"""Topilmani odam tiliga o'girish — shablon izohi va LLM tahlili.

VAZIFA BO'LINISHI:
  * ANIQLASH — `rules.py`, sof arifmetika. LLM u yerga aralashmaydi, chunki
    "40 litr yetishmayapti" degan xulosa hisobdan chiqadi, taxmindan emas.
  * IZOHLASH — har bir anomaliyaga `template_explanation`, LLM'siz.
  * TAHLIL — butun hisobot bo'yicha BITTA LLM chaqiruvi (`analyze`).

NIMA UCHUN HAR ANOMALIYAGA ALOHIDA LLM CHAQIRUVI EMAS (24.08.2026 o'lchovi):
    4 ta anomaliyaga 4 ta chaqiruv    -> 54.5 s
    bitta umumiy tahlil               -> ~20 s
Ollama bitta model uchun so'rovlarni NAVBAT bilan bajaradi, shuning uchun
`asyncio.gather` hech narsa tejamasdi. Ammo asosiy sabab tezlik emas:

Shablon izohi anomaliyaning belgilarini allaqachon to'liq aytadi ("spidometr
orqaga qaytgan, hujjatni tekshirish kerak"). LLM unga uslub qo'shardi,
MA'LUMOT emas. LLM faqat o'zi qila oladigan ish — bir necha yozuvni BIRGA
ko'rib bog'lanishni topish: "4 topilmadan 3 tasi spidometr xatosi, ehtimol
bitta sabab; muhimrog'i 93 hujjatda balans umuman tekshirilmagan".

Shu sababli LLM shu yerga qo'yildi va har-hujjat izohidan olib tashlandi.

LLM izohi olinmasa yoki tekshiruv chegaralariga zid bo'lsa
`AnalysisUnavailable` ko'tariladi va endpoint 503 qaytaradi.
AI izohi shablon bilan almashtirilmaydi.

LLM GA RAQAM HISOBLATILMAYDI. Promptga faqat TAYYOR faktlar boradi va
"yangi raqam o'ylab topma" deb qat'iy aytiladi. Bo'shliqlar ham yuboriladi —
LLM "muammo yo'q" deb xulosa qilib yubormasligi uchun.
"""

from __future__ import annotations

import json
import logging
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from oil_detection import config, texts
from oil_detection.texts import t

logger = logging.getLogger(__name__)


class AnalysisUnavailable(RuntimeError):
    """LLM tahlil yozib bera olmadi — router buni 503 ga aylantiradi.

    NIMA UCHUN XATO, SHABLON EMAS. Ilgari LLM ishlamasa tahlil shablon
    matni bilan to'ldirilardi va javob 200 bo'lib qaytardi. Bu loyihada
    tahlilning O'ZI mahsulot: shablon matni "AI tahlil qildi" degan
    taassurot berardi, aslida esa hech qanday tahlil bo'lmasdi.

    Endi javob YO to'liq (LLM tahlili bilan), YO umuman yo'q. Frontend
    503 ni ko'rib "xatolik yuz berdi, keyinroq urinib ko'ring" deydi va
    foydalanuvchi qayta so'raydi.

    Hisobotning QOLGAN hamma qismi (ballar, marshrut, topilmalar) baribir
    arifmetikadan chiqadi va u yo'qolmaydi — shunchaki bu javobda
    yuborilmaydi.
    """


# PROMPT QISQA — javob yozish tezligi ~10 token/s (gemma4:31b, ngrok),
# ya'ni har bir ortiqcha jumla 5-10 soniya. To'rt jumla butun hisobotni
# qoplashga yetadi.
PROMPT = """Sen transport parki nazoratchisiga yordam beradigan yordamchisan.

Quyida yoqilg'i tekshiruvining ALLAQACHON HISOBLANGAN natijasi berilgan.
Sen raqamlarni qayta hisoblamaysan.

{language_rule}

Vazifang: 4 ta qisqa jumla yoz — YUQORIDA KO'RSATILGAN TILDA.
1-jumla: umumiy manzara — nechta yozuv va mashina tekshirildi, shundan nechta mashinada ortiqcha sarf (norma/limitdan oshish) va nechta mashina/yozuvda shubhali holat (topilma) aniqlandi.
2-jumla: shubhali holatlar va ortiqcha sarf turlari bo'yicha asosiy naqsh (masalan: balans farqi, spidometr xatosi, normadan ortiqcha sarf va qaysi mashinalarda ko'proq).
         Topilma nol va tekshiruv bo'shliqlari bo'lsa, muammo yo'qligi
         TASDIQLANMAGANINI ayt. "Jiddiy kamchilik qayd etilmadi" dema.
3-jumla: "tekshirilmagan" bo'limidagi eng katta bo'shliq — qaysi ustun
         to'ldirilmagani va shu sababli NIMA tekshirilmay qolgani.
4-jumla: nazoratchi nima qilishi kerak.

QAT'IY QOIDALAR:
- Faqat berilgan raqamlardan foydalan. Yangi raqam O'YLAB TOPMA.
- Ayblov qilma: "o'g'irlagan" dema, "tekshirish kerak" de.
- "Muammo topilmadi" degan xulosani bo'shliqlarni aytmasdan chiqarma.
- Tekshirilmagan yozuv bor bo'lsa "muammo yo'q", "hammasi joyida",
  "xavf yo'q" yoki "jiddiy kamchiliklar qayd etilmadi" dema.
  "Tekshirilgan qismda topilma aniqlanmadi; qolgan tekshiruv noma'lum" deb ajrat.
- Sarlavha va ro'yxat belgisi yozma — faqat to'rt jumlaning o'zini yoz.

NATIJA (JSON):
{facts}

TAHLIL:"""

#: Belgi turi -> izoh oxiridagi tavsiya. Turlar `rules.py` da belgilangan.
ADVICE = {
    "IMPOSSIBLE": " Bunday qiymat bo'lishi mumkin emas — hujjatni tekshirish kerak.",
    "MISMATCH": " Raqamlar bir-biriga zid — hujjatni tekshirish kerak.",
    "OVER_LIMIT": " Limit oshgan — sababi aniqlanishi kerak.",
    "OVER_NORM": " Normadan oshgan — sababi aniqlanishi kerak.",
}


def template_explanation(
    anomaly: dict[str, Any], lang: str = texts.DEFAULT_LANG
) -> str:
    """LLM'siz izoh — belgilar tafsilotlarini birlashtiradi.

    Bu ZAXIRA emas, ASOS: LLM o'chirilgan bo'lsa ham javob to'liq mazmunli
    bo'lishi kerak.
    """
    flags = anomaly.get("flags") or []
    if not flags:
        return t(lang, "expl.no_finding")

    vehicle = anomaly.get("vehicle") or {}
    driver = anomaly.get("driver") or {}
    head_parts = []
    if vehicle.get("plate_number"):
        head_parts.append(t(lang, "expl.vehicle", plate=vehicle["plate_number"]))
    if driver.get("full_name"):
        head_parts.append(t(lang, "expl.driver", name=driver["full_name"]))
    if anomaly.get("document_number"):
        head_parts.append(
            t(lang, "expl.document", number=anomaly["document_number"]))
    head = ", ".join(head_parts)

    details = " ".join(flag["detail"] for flag in flags)
    tail = ""
    for kind in anomaly.get("kinds") or []:
        if f"advice.{kind}" in texts.MESSAGES:
            tail = t(lang, f"advice.{kind}")
            break
    return f"{head}: {details}{tail}".strip() if head else f"{details}{tail}".strip()

def _flag_title(code: str, lang: str = texts.DEFAULT_LANG) -> str:
    from oil_detection import rules

    return rules.flag_title(code, lang)


def _finding_titles(counts: dict[str, int] | None, lang: str = texts.DEFAULT_LANG) -> list[str]:
    from oil_detection import rules

    codes = [c for c in (counts or {}) if rules.FLAG_KIND.get(c, rules.KIND_DATA_GAP) != rules.KIND_DATA_GAP]
    return [_flag_title(code, lang) for code in (codes or list(counts or {}))[:4]]


def _titled(
    counts: dict[str, int] | None, lang: str = texts.DEFAULT_LANG
) -> dict[str, int]:
    """Belgi kodlarini o'zbekcha nomga almashtiradi."""
    return {_flag_title(code, lang): n for code, n in (counts or {}).items()}


def _facts_for_llm(
    report: dict[str, Any], limit: int, lang: str = texts.DEFAULT_LANG
) -> dict[str, Any]:
    """LLM ga faqat qaror uchun kerakli maydonlar yuboriladi.

    Butun hisobotni yuborish prompt'ni kattalashtiradi va javobni
    sekinlashtiradi; `evidence` ichidagi xom qiymatlar tahlil uchun kerak emas.

    BO'SHLIQLAR HAM YUBORILADI (`tekshirilmagan`) — usiz LLM "muammo yo'q"
    deb xulosa qilib yuborardi, holbuki ko'p yozuv umuman tekshirilmagan.
    """
    summary = report.get("summary") or {}
    anomalies = (report.get("anomalies") or [])[:limit]
    flagged_vehicles = [v for v in (report.get("vehicles") or []) if v.get("finding_records")][:limit]

    return {
        "davr": report.get("period"),
        "umumiy": {
            "tekshirilgan_yozuv": summary.get("checked_records"),
            "topilmali_yozuv": summary.get("finding_records"),
            "normaga_solishtirilgan": summary.get("checked_against_norm"),
            "hisobdan_tashqari_litr": summary.get("total_unaccounted_liters"),
            "limitdan_oshgan_litr": summary.get("total_over_limit_liters"),
            "normadan_ortiqcha_litr": summary.get("total_excess_liters"),
            "mashina": summary.get("vehicles"),
            "ortiqcha_sarflagan_mashina": summary.get("overconsuming_vehicles"),
            "shubhali_topilmali_mashina": summary.get("vehicles_with_finding"),
            "haydovchi": summary.get("drivers"),
        },
        # Kalitlar KOD emas, o'zbekcha NOM: LLM javobida `FUEL_ISSUED_UNKNOWN`
        # kabi kodlarni takrorlab, jumlani g'aliz qilib yubormasin.
        "topilma_turlari": _titled(summary.get("flag_counts"), lang),
        "tekshirilmagan": _titled(summary.get("data_gap_counts"), lang),
        "ortiqcha_va_shubhali_mashinalar": [
            {
                "mashina": (v.get("vehicle") or {}).get("plate_number"),
                "topilma_soni": v.get("finding_records"),
                "normadan_ortiqcha_litr": v.get("excess_liters"),
                "hisobdan_tashqari_litr": v.get("unaccounted_liters"),
                "limitdan_oshgan_litr": v.get("over_limit_liters"),
                "belgilar": _finding_titles(v.get("flags"), lang),
            }
            for v in flagged_vehicles
        ],
        "eng_muhim_yozuvlar": [
            {
                "mashina": (a.get("vehicle") or {}).get("plate_number"),
                "haydovchi": (a.get("driver") or {}).get("full_name"),
                "hujjat": a.get("document_number"),
                "hisobdan_tashqari_litr": a.get("unaccounted_liters"),
                "normadan_ortiqcha_litr": a.get("excess_liters"),
                "belgilar": [f["code"] for f in (a.get("flags") or [])],
            }
            for a in anomalies
        ],
    }


def unsupported_clean_bill(report: dict[str, Any], answer: str) -> bool:
    """Reject concrete no-problem assertions when checks were unavailable."""
    gaps = (report.get('summary') or {}).get('data_gap_counts') or {}
    if not any(isinstance(v,(int,float)) and v > 0 for v in gaps.values()):
        return False
    value = answer.casefold().translate(str.maketrans({'‘':"'",'’':"'",'`':"'",'ʻ':"'",'ʼ':"'"}))
    patterns = (
        r"\b(?:jiddiy\s+)?(?:muammo(?:lar)?|kamchilik(?:lar)?|xavf)\s+(?:yo'q|mavjud emas|aniqlanmadi|qayd etilmadi)\b",
        r"\bhammasi\s+joyida\b", r"\b(?:no problems|no issues|everything is fine)\b",
        r"\b(?:проблем нет|нарушений нет|всё в порядке|все в порядке)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern,value):
            tail=value[match.end():match.end()+45].lstrip(' \"\'')
            if re.match(r"(?:degani emas|de(?:b|ya) (?:aytib )?bo'lmaydi|degan xulosa.*mumkin emas)",tail):
                continue
            return True
    return False


async def analyze(
    report: dict[str, Any],
    *,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Butun hisobotni LLM bilan tahlil qiladi va `report` ga yozadi (joyida).

    Butun hisobot uchun bitta chaqiruv, zarur bo'lsa bitta cheklangan tuzatish.
    Har anomaliyaga alohida chaqiruv emas. Sababi modul
    docstring'ida: shablon izohi har bir yozuvni allaqachon tushuntiradi,
    LLM esa ular ORASIDAGI bog'lanishni ko'radi.

    LLM javob bermasa `AnalysisUnavailable` ko'tariladi — shablonga
    tushilmaydi.
    """
    top = limit if limit is not None else config.LLM_EXPLAIN_LIMIT

    # Kech import: Ollama o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # chatbot config (atil_chatbot/config.py)
    from ollama_client import ask_llm

    # Til ko'rsatmasi chatbotnikidan — bitta qoida uch xizmatda bir xil.
    prompt = PROMPT.format(
        language_rule=texts.llm_instruction(lang),
        facts=json.dumps(
            _facts_for_llm(report, top, lang), ensure_ascii=False, indent=2, default=str
        )
    )
    try:
        text = await ask_llm(
            prompt,
            {
                "options": {
                    "temperature": 0.2,
                    "num_predict": 280,
                    "num_ctx": DEFAULT_NUM_CTX,
                },
                "think": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 — tahlil yo'q = javob yo'q
        logger.warning("LLM tahlili olinmadi: %s", str(exc)[:160])
        raise AnalysisUnavailable("Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring") from exc

    cleaned = (text or "").strip()
    if not cleaned:
        logger.warning("LLM bo'sh javob qaytardi")
        raise AnalysisUnavailable("Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring")

    if unsupported_clean_bill(report, cleaned):
        repair = prompt + "\nTUZATISH: tekshiruv bo‘shliqlari mavjud. Muammo yo‘qligini tasdiqlama. Faqat topilma chiqmaganini va qaysi tekshiruv bajarilmaganini ajratib yoz."
        try:
            replacement = await asyncio.wait_for(ask_llm(repair, {
                'timeout':30,'think':False,'enable_thinking':False,
                'options':{'temperature':0,'num_predict':250,'num_ctx':DEFAULT_NUM_CTX},
            }),timeout=30)
            cleaned = (replacement or '').strip()
        except Exception as exc:
            raise AnalysisUnavailable('AI izohi tekshiruv chegaralariga mos kelmadi. Qayta urinib ko‘ring.') from exc
        if not cleaned or unsupported_clean_bill(report, cleaned):
            raise AnalysisUnavailable('AI izohi tekshirilmagan yozuvlarni to‘g‘ri ajratmadi. Qayta urinib ko‘ring.')

    report["analysis"] = {
        "text": cleaned,
        "anomalies_considered": min(top, len(report.get("anomalies") or [])),
    }
