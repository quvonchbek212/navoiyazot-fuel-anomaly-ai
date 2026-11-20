"""Yoqilg'i tekshiruvi endpointi.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi — bu yerda alohida
`FastAPI()` yaratilmaydi, aks holda Swagger bir nechta bo'lib ketardi.
Butun ilova HTTP Basic bilan yopiq (`security.py`), shuning uchun bu yerda
autorizatsiya qayta yozilmaydi.

`/scan` umumiy reytingni, `/investigate` esa bitta yo'l varaqasi bo'yicha
dalil izlaydigan AI tekshiruvini qaytaradi.

SANALAR MAJBURIY. Sukut bo'yicha "oxirgi 30 kun" qilinmadi, chunki u ham
o'ylab topilgan qiymat bo'lardi: hisobot qaysi davr uchun kerakligini
chaqiruvchi biladi, dastur emas.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from oil_detection import detector, texts
from oil_detection.explain import AnalysisUnavailable, analyze
from oil_detection.models import FuelReport
from oil_detection.queries import OilDataError
from oil_detection.investigation_agent import investigate, WaybillNotFound
from oil_detection.investigation_models import InvestigationRequest, InvestigationReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oil-detection", tags=["Yoqilg'i anomaliyasi"])


@router.get('/gps-daily', summary='Kunlik GPS masofasi va shu reyslar sarfini solishtirish')
async def gps_daily(day: date = Query(..., description='Toshkent kuni, YYYY-MM-DD')):
    from oil_detection import gps_daily as daily
    try:
        result = await run_in_threadpool(daily.report, day)
    except OilDataError:
        raise HTTPException(503, 'Kunlik GPS va yoqilg‘i ma’lumotini hozir o‘qib bo‘lmadi. Qayta urinib ko‘ring.')
    return await daily.enrich(result)


@router.post(
    "/investigate", response_model=InvestigationReport,
    summary="Reys bo'yicha dalil izlaydigan yoqilg'i AI agenti",
    responses={404: {"description": "Yo'l varaqasi topilmadi"},
               503: {"description": "Baza yoki AI tekshiruvi vaqtincha mavjud emas"}},
)
async def investigate_waybill(request: InvestigationRequest) -> InvestigationReport:
    """Yuk, o'xshash qatnovlar, balans va tarixni tekshiradi.

    Agent keyingi tekshiruvni dalillarga qarab tanlaydi. Har xulosada
    `evidence_ids`, tekshiruv maqsadlari `steps`, ko'rilmagan manbalar
    `unvisited_tools` da. Noma'lum yuk yuksiz deb olinmaydi. Sarfni o'rganuvchi
    model yo'q. Har bir so'rov mustaqil; bazaga yozilmaydi.
    """
    try:
        return await investigate(request)
    except WaybillNotFound:
        raise HTTPException(404, {"uz": "Yo'l varaqasi topilmadi", "ru": "Путевой лист не найден", "en": "Waybill not found"}[request.lang])
    except (OilDataError, AnalysisUnavailable):
        raise HTTPException(503, {"uz": "AI tekshiruvi bajarilmadi. Keyinroq urinib ko'ring.",
                                  "ru": "Проверка ИИ недоступна. Повторите позже.",
                                  "en": "AI investigation unavailable. Try again later."}[request.lang])


@router.get(
    "/scan",
    response_model=FuelReport,
    summary="Yoqilg'i bo'yicha ortiqcha sarf va shubhali holatlar",
    responses={
        400: {"description": "Sana oralig'i noto'g'ri"},
        503: {"description": "Tahlilni LLM yozib bera olmadi yoki bazaga ulanib bo'lmadi — vaqtinchalik holat, qayta urinish mumkin"},
    },
)
async def scan(
    date_from: date = Query(
        ..., description="Boshlanish sanasi (YYYY-MM-DD), shu kun ham kiradi",
        examples=["2026-08-01"]),
    date_to: date = Query(
        ..., description="Tugash sanasi (YYYY-MM-DD), shu kun ham kiradi",
        examples=["2026-08-31"]),
    lang: Literal["uz", "ru", "en"] = Query(
        "uz",
        description="**Javob tili.** Matnlarning HAMMASI shu tilda chiqadi: "
                    "belgi nomi (`flags[].title`) va tafsiloti "
                    "(`flags[].detail`), anomaliya izohi, "
                    "`data_quality.notes` va LLM tahlili.\n\n"
                    "**Kodlar tarjima qilinmaydi** — `flags[].code`, "
                    "`flags[].kind`, jadval va ustun nomlari uch tilda ham bir "
                    "xil: ularni dastur o'qiydi.",
    ),
) -> FuelReport:
    """Sana oralig'ida **ortiqcha sarflagan va shubhali olgan**larni topadi.

    Javobda uchta kesim:

    | Bo'lim | Savol |
    |---|---|
    | `vehicles` | qaysi **mashina** |
    | `drivers` | qaysi **haydovchi** |
    | `anomalies` | o'sha raqam **qaysi hujjatdan** chiqqani |

    **Uch xil litr, uchtasi ham o'lchangan:**

    | Maydon | Manba | Ma'nosi |
    |---|---|---|
    | `unaccounted_liters` | hujjatning o'zi | hisobdan tashqari: balans farqi, hujjatsiz quyish |
    | `over_limit_liters` | `fuel_limit` | kunlik/oylik limitdan oshgan |
    | `excess_liters` | `fuel_norm` | normadan (tolerans bilan) ortiqcha |

    Reyting `unaccounted_liters` dan boshlab saralanadi: normadan ortiqcha
    sarflashning texnik sababi bo'lishi mumkin, hujjatda litr yo'qolishining esa yo'q.

    **Nima bilan solishtirilishini baza aytadi.** `fuel_norm` — norma
    (100 km ga yoki motor-soatga litr) va uning `tolerance_percent` i;
    `fuel_limit` — haydovchi yoki mashinaga qo'yilgan kunlik/oylik chegara.
    Kodda birorta ham o'ylab topilgan meyor yo'q: qolgan qoidalar
    tenglamaning o'zi (qaytgan yoqilg'i mavjudidan ko'p bo'la olmaydi,
    litr manfiy bo'la olmaydi, spidometr orqaga qaytmaydi).

    **Norma belgilanmagan mashinaga hukm chiqarilmaydi** — `NO_NORM_DEFINED`
    deb yozib qo'yiladi. Nechta yozuv normaga solishtirilgani
    `summary.checked_against_norm` da ko'rinadi.

    **Topilma va bo'shliq — ikki xil narsa.** `summary.flag_counts` nima
    NOTO'G'RI ekanini aytadi, `summary.data_gap_counts` esa nima
    TEKSHIRILMAGANINI: qaysi ustun to'ldirilmagani uchun qaysi qoida
    ishlamay qolgani. Ikkinchisisiz "topilma yo'q" javobi "muammo yo'q"
    bo'lib ko'rinardi.

    **Aniqlash arifmetika bilan, tahlil LLM bilan.** Har bir belgida
    `evidence` bor — hisobda ishlatilgan xom qiymatlar, ya'ni natijani
    qo'lda qayta tekshirib ko'rish mumkin. Har bir anomaliyaning
    `explanation` maydoni shablon bilan yoziladi (LLM'siz), LLM esa butun
    hisobot bo'yicha BITTA tahlil yozadi (`analysis`): umumiy manzara,
    takrorlanadigan naqsh, eng katta bo'shliq va tavsiya. **Tahlil
    shablonga tushmaydi**: LLM javob bermasa endpoint 503 qaytaradi.

    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    if date_from > date_to:
        raise HTTPException(400, "`date_from` `date_to` dan katta bo'lmasligi kerak")

    try:
        result = await run_in_threadpool(
            detector.report,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            lang=lang,
        )
    except OilDataError as exc:
        # Baza yotgan bo'lsa 500 emas, 503: bu vaqtinchalik holat va
        # chaqiruvchi qayta urinishi mumkin.
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")

    # TAHLIL DOIM YOZILADI va u FAQAT LLM dan keladi. Shablonga tushish
    # yo'q: LLM javob bermasa 503 qaytadi va frontend "keyinroq urinib
    # ko'ring" deydi.
    try:
        await analyze(result, lang=lang)
    except AnalysisUnavailable as exc:
        raise HTTPException(503, str(exc))

    return FuelReport(**result)
