"""Javobdagi hamma matn — uch tilda (uz, ru, en).

NIMA UCHUN BU FAYL BOR. Javobning yarmi matn: belgi nomi (`flags[].title`),
tafsiloti (`flags[].detail`), anomaliya izohi, `data_quality.notes`. Ular
`rules.py`, `detector.py` va `explain.py` ning o'nlab joyida f-string
bo'lib yozilgan edi va faqat o'zbekcha chiqardi. So'rovda `?lang=`
berilganda javob TO'LIQ o'sha tilda bo'lishi kerak.

Marshrut optimizatsiyasi va vehicle_selection dagi `texts.py` bilan bir
xil tuzilma: kalit -> uchta til.

KODLAR TARJIMA QILINMAYDI. `flags[].code`, `flags[].kind`, jadval va
ustun nomlari uch tilda ham bir xil qoladi: ularni dastur o'qiydi va til
o'zgarganda chaqiruvchining filtri buzilmasligi kerak.

RAQAM VA SANA SHU YERDA FORMATLANMAYDI — ular chaqiruvchi tomonda
tayyorlanadi va kalitga parametr bo'lib kiradi. Sabab: `:g` va `:+.2f`
kabi formatlar qoidaning o'zida ma'noga ega (masalan `+` belgisi
chetlanish yo'nalishini ko'rsatadi).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# `core.lang` atil_chatbot ichida yassi nom bilan import qiladi.
_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from core.lang import answer_instruction, status_dictionary  # noqa: E402

#: Qo'llab-quvvatlanadigan tillar — boshqa modullar bilan bir xil.
LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"


def normalize(lang: str | None) -> str:
    """Noma'lum yoki bo'sh til sukut tilga tushadi."""
    value = (lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def transport_name(code: str | None, lang: str) -> str | None:
    """Transport turi kodining o'qiladigan nomi.

    Manba — chatbotning lug'ati (`core.lang.status_dictionary`), marshrut
    modulidagi bilan bir xil. `vehicle_selection/labels.py` dan olinmadi:
    modullar bir-biriga bog'lanmasligi kerak, chatbot lug'ati esa
    ikkalasiga ham umumiy.

    Noma'lum kod uz/ru da KODNING O'ZI bo'lib qaytadi — tarjima o'ylab
    topilmaydi. Ingliz tilida kodning o'zi inglizcha so'z, shuning uchun
    faqat o'qishga qulay yoziladi.
    """
    if not code:
        return None
    name = status_dictionary(lang).get(code)
    if name:
        return name
    if lang == "en":
        return code.replace("_", " ").lower()
    return code


def llm_instruction(lang: str) -> str:
    """LLM promptiga qo'shiladigan til ko'rsatmasi — chatbotnikidan."""
    return answer_instruction(normalize(lang))


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Kalitni tanlangan tilda qaytaradi.

    Kalit topilmasa KALITNING O'ZI qaytadi — javob bo'sh qolmaydi va
    yetishmayotgan matn darrov ko'zga tashlanadi.
    """
    row = MESSAGES.get(key)
    if row is None:
        return key
    text = row.get(normalize(lang)) or row[DEFAULT_LANG]
    return text.format(**kwargs) if kwargs else text


MESSAGES: dict[str, dict[str, str]] = {
    "flag.FUEL_UNIT_UNVERIFIED": {"uz":"Yoqilg‘i birligi tasdiqlanmagan", "ru":"Единица топлива не подтверждена", "en":"Fuel unit unverified"},
    "detail.fuel_unit_unverified": {"uz":"Yoqilg‘i turi yoki uning litr birligi tasdiqlanmagan. Litr sarfi va normadan oshish hisoblanmadi.", "ru":"Тип топлива или единица в литрах не подтверждены. Расход в литрах и превышение не рассчитаны.", "en":"Fuel type or litre unit is unverified. Litres and excess consumption were not calculated."},
    "flag.CALCULATION_MODE_UNSUPPORTED": {"uz":"Hisoblash rejimi aniqlashtirilishi kerak", "ru":"Режим расчёта требует уточнения", "en":"Calculation mode needs clarification"},
    "detail.calculation_mode_unsupported": {"uz":"Rejim noma’lum yoki masofa va motor-soat birga hisoblanadi. Bitta masofa normasi qo‘llanmadi.", "ru":"Режим неизвестен или объединяет пробег и моточасы. Одна норма пробега не применена.", "en":"Mode is unknown or combines distance and engine hours. A distance-only norm was not applied."},
    "flag.NORM_TOLERANCE_UNKNOWN": {"uz":"Normaning ruxsat etilgan farqi noma’lum", "ru":"Допуск нормы неизвестен", "en":"Norm tolerance unknown"},
    "detail.norm_tolerance_unknown": {"uz":"Ruxsat etilgan farq kiritilmagan yoki yaroqsiz; nol deb olinmadi va normadan oshish hukmi chiqarilmadi.", "ru":"Допуск отсутствует или неверен; он не принят за ноль, вывод о превышении не сделан.", "en":"Tolerance is absent or invalid; it was not assumed zero and no excess verdict was issued."},

    # ------------------------------------------------------- Belgi nomlari
    "flag.RETURN_EXCEEDS_AVAILABLE": {
        "uz": "Qaytgan yoqilg'i mavjudidan ko'p",
        "ru": "Возвращённого топлива больше, чем было доступно",
        "en": "More fuel returned than was available",
    },
    "flag.NEGATIVE_VALUE": {
        "uz": "Manfiy qiymat", "ru": "Отрицательное значение",
        "en": "Negative value"},
    "flag.ODOMETER_BACKWARDS": {
        "uz": "Spidometr orqaga qaytgan",
        "ru": "Одометр пошёл назад",
        "en": "The odometer went backwards",
    },
    "flag.BALANCE_MISMATCH": {
        "uz": "Yoqilg'i balansi to'g'ri kelmadi",
        "ru": "Топливный баланс не сходится",
        "en": "The fuel balance does not add up",
    },
    "flag.DB_DEVIATION_MISMATCH": {
        "uz": "Bazadagi chetlanish qayta hisobga mos kelmadi",
        "ru": "Отклонение в базе не совпало с пересчётом",
        "en": "The deviation in the database does not match the recomputation",
    },
    "flag.SOURCE_LITERS_MISMATCH": {
        "uz": "Ikki manba turli sarf ko'rsatyapti",
        "ru": "Два источника показывают разный расход",
        "en": "Two sources report different consumption",
    },
    "flag.CONSUMPTION_OVER_NORM": {
        "uz": "Normadan ortiqcha sarf",
        "ru": "Расход выше нормы",
        "en": "Consumption above the norm",
    },
    "flag.LIMIT_EXCEEDED": {
        "uz": "Yoqilg'i limiti oshib ketdi",
        "ru": "Превышен лимит топлива",
        "en": "The fuel limit was exceeded",
    },
    "flag.NO_NORM_DEFINED": {
        "uz": "Norma belgilanmagan", "ru": "Норма не задана",
        "en": "No norm is defined"},
    "flag.DISTANCE_UNKNOWN": {
        "uz": "Masofa va motor-soat noma'lum",
        "ru": "Пробег и моточасы неизвестны",
        "en": "Distance and engine hours are unknown",
    },
    "flag.NO_TRIP_BOUND": {
        "uz": "Reysga bog'lanmagan", "ru": "Не привязано к рейсу",
        "en": "Not bound to a trip"},
    "flag.FUEL_ISSUED_UNKNOWN": {
        "uz": "Quyilgan yoqilg'i yozilmagan",
        "ru": "Заправка не записана",
        "en": "The fuel issued was not recorded",
    },

    # ------------------------------------------------- Belgi tafsilotlari
    "detail.balance_mismatch": {
        "uz": "Hujjatda {reported} L sarf yozilgan, bakdagi qoldiq bo'yicha esa "
              "{balance} L chiqadi (farq {diff} L). Hisob: chiqishda {start} + "
              "quyilgan {issued} - qaytgan {end}.",
        "ru": "В документе записан расход {reported} L, а по остатку в баке "
              "получается {balance} L (разница {diff} L). Расчёт: при выезде "
              "{start} + заправлено {issued} - возвращено {end}.",
        "en": "The document records {reported} L consumed, but the tank balance "
              "gives {balance} L (difference {diff} L). The arithmetic: "
              "{start} at departure + {issued} issued - {end} returned.",
    },
    "detail.return_exceeds": {
        "uz": "Qaytishda bakda {end} L, holbuki mavjud bo'lishi mumkin bo'lgani "
              "{available} L (chiqishda {start} + quyilgan {issued}). "
              "Ortiqcha {over} L — hujjatsiz quyish yoki ko'rsatkich xatosi.",
        "ru": "При возврате в баке {end} L, хотя доступно могло быть {available} L "
              "(при выезде {start} + заправлено {issued}). Лишние {over} L — "
              "заправка без документа или ошибка показания.",
        "en": "On return the tank holds {end} L, although at most {available} L "
              "could have been available ({start} at departure + {issued} "
              "issued). The extra {over} L means undocumented refuelling or a "
              "reading error.",
    },
    "detail.negative_value": {
        "uz": "Manfiy qiymat(lar) topildi: {values}. Yoqilg'i miqdori manfiy "
              "bo'lishi mumkin emas.",
        "ru": "Найдены отрицательные значения: {values}. Количество топлива не "
              "может быть отрицательным.",
        "en": "Negative value(s) found: {values}. A fuel amount cannot be negative.",
    },
    "detail.odometer_backwards": {
        "uz": "Qaytishdagi spidometr ({end} km) chiqishdagidan ({start} km) "
              "kichik — ko'rsatkich orqaga qaytgan.",
        "ru": "Одометр при возврате ({end} км) меньше, чем при выезде "
              "({start} км) — показание пошло назад.",
        "en": "The odometer on return ({end} km) is lower than at departure "
              "({start} km) — the reading went backwards.",
    },
    "detail.over_norm": {
        "uz": "{scale}. Tolerans {tolerance}% bilan ruxsat etilgani {allowed} L, "
              "sarflangani {consumed} L — normadan {excess} L ({percent}%) ortiq.",
        "ru": "{scale}. С допуском {tolerance}% разрешено {allowed} L, "
              "израсходовано {consumed} L — выше нормы на {excess} L ({percent}%).",
        "en": "{scale}. With a {tolerance}% tolerance {allowed} L was allowed, "
              "{consumed} L was used — {excess} L ({percent}%) above the norm.",
    },
    "detail.scale_engine_hour": {
        "uz": "{hours} motor-soatda soatiga {actual} L sarflangan, norma {norm} L",
        "ru": "За {hours} моточасов израсходовано {actual} L в час, норма {norm} L",
        "en": "{actual} L per hour used over {hours} engine hour(s), norm {norm} L",
    },
    "detail.scale_distance": {
        "uz": "{km} km da 100 km ga {actual} L sarflangan, norma {norm} L",
        "ru": "На {km} км израсходовано {actual} L на 100 км, норма {norm} L",
        "en": "{actual} L per 100 km used over {km} km, norm {norm} L",
    },
    "detail.scale_expected": {
        "uz": "{consumed} L sarflangan, kutilgan sarf {expected} L",
        "ru": "Израсходовано {consumed} L, ожидаемый расход {expected} L",
        "en": "{consumed} L used, expected consumption {expected} L",
    },
    "detail.db_deviation": {
        "uz": "Bazada chetlanish {theirs}%, qayta hisobda {ours}%. Norma yozuvdan "
              "keyin o'zgargan yoki bazadagi hisob eskirgan bo'lishi mumkin.",
        "ru": "В базе отклонение {theirs}%, при пересчёте {ours}%. Возможно, норма "
              "изменилась после записи или расчёт в базе устарел.",
        "en": "The database shows a {theirs}% deviation, the recomputation gives "
              "{ours}%. The norm may have changed after the record, or the "
              "stored figure is stale.",
    },
    "detail.limit_exceeded": {
        "uz": "{subject} uchun {window} limit {max} L. {period} da {count} ta "
              "yozuvda {used} L sarflangan — {over} L oshgan.",
        "ru": "Для «{subject}» {window} лимит {max} L. За {period} в {count} "
              "записях израсходовано {used} L — превышение на {over} L.",
        "en": "The {window} limit for the {subject} is {max} L. Over {period}, "
              "{count} record(s) used {used} L — {over} L over the limit.",
    },
    "detail.source_mismatch": {
        "uz": "Bir voqea ikki jadvalda turlicha yozilgan: {parts} (farq {diff} L). "
              "Qaysi biri to'g'ri ekani tekshirilishi kerak.",
        "ru": "Одно событие записано по-разному в двух таблицах: {parts} (разница "
              "{diff} L). Нужно проверить, какая запись верна.",
        "en": "One event is recorded differently in two tables: {parts} "
              "(difference {diff} L). Which one is correct must be checked.",
    },
    "detail.distance_unknown": {
        "uz": "Masofa ham, motor-soat ham aniqlanmadi — sarfni normaga "
              "solishtirib bo'lmadi.",
        "ru": "Ни пробег, ни моточасы не определены — сравнить расход с нормой "
              "невозможно.",
        "en": "Neither distance nor engine hours could be determined — "
              "consumption could not be compared with the norm.",
    },
    "detail.no_norm": {
        "uz": "Mashinaga sarf normasi belgilanmagan (`fuel_norm` da yozuv yo'q) — "
              "normadan chetlanish tekshirilmadi.",
        "ru": "Для машины не задана норма расхода (нет записи в `fuel_norm`) — "
              "отклонение от нормы не проверялось.",
        "en": "No consumption norm is set for the vehicle (no `fuel_norm` record) "
              "— deviation from the norm was not checked.",
    },
    "detail.no_trip": {
        "uz": "Yozuv reysga bog'lanmagan — yoqilg'i qaysi ish uchun sarflangani "
              "noma'lum.",
        "ru": "Запись не привязана к рейсу — неизвестно, на какую работу "
              "израсходовано топливо.",
        "en": "The record is not bound to a trip — what the fuel was used for is "
              "unknown.",
    },
    "detail.fuel_issued_unknown": {
        "uz": "Yo'lda quyilgan yoqilg'i yozilmagan (`fuel_issued_liters` bo'sh) — "
              "bak balansi tekshirilmadi.",
        "ru": "Заправка в пути не записана (`fuel_issued_liters` пуст) — баланс "
              "бака не проверялся.",
        "en": "Fuel issued en route was not recorded (`fuel_issued_liters` is "
              "empty) — the tank balance was not checked.",
    },

    # ------------------------------------------------------- Sarf asoslari
    "basis.expected": {
        "uz": "bazadagi kutilgan sarf", "ru": "ожидаемый расход из базы",
        "en": "expected consumption from the database"},
    "basis.distance": {
        "uz": "100 km ga litr", "ru": "литров на 100 км",
        "en": "litres per 100 km"},
    "basis.engine_hour": {
        "uz": "motor-soatga litr", "ru": "литров на моточас",
        "en": "litres per engine hour"},
    "basis.waybill_norm": {
        "uz": "yo'l varaqasidagi norma", "ru": "норма из путевого листа",
        "en": "the norm from the waybill"},

    # ------------------------------------------------------------- Mayda
    "misc.daily": {"uz": "kunlik", "ru": "суточный", "en": "daily"},
    "misc.monthly": {"uz": "oylik", "ru": "месячный", "en": "monthly"},
    "misc.driver": {"uz": "Haydovchi", "ru": "Водитель", "en": "driver"},
    "misc.vehicle": {"uz": "Mashina", "ru": "Машина", "en": "vehicle"},

    # ------------------------------------------------- data_quality.notes
    "note.row_limit": {
        "uz": "`{table}` dan {limit} ta yozuv o'qildi — chegaraga yetildi, "
              "davrni qisqartiring, aks holda natija to'liq emas.",
        "ru": "Из `{table}` прочитано {limit} записей — достигнут лимит, "
              "сократите период, иначе результат неполный.",
        "en": "{limit} record(s) were read from `{table}` — the limit was "
              "reached; shorten the period or the result is incomplete.",
    },
    "note.duplicates": {
        "uz": "{count} ta voqea ikkala jadvalda ham yozilgan — sarf litri "
              "yig'indiga bir marta qo'shildi.",
        "ru": "{count} событий записаны в обеих таблицах — литры расхода учтены "
              "в сумме один раз.",
        "en": "{count} event(s) are recorded in both tables — their litres were "
              "added to the total only once.",
    },
    "note.without_norm": {
        "uz": "{count} ta yozuvda norma topilmadi — ularda normadan chetlanish "
              "TEKSHIRILMADI. Norma `fuel_norm` jadvalidan olinadi.",
        "ru": "В {count} записях норма не найдена — отклонение от нормы для них "
              "НЕ ПРОВЕРЯЛОСЬ. Норма берётся из таблицы `fuel_norm`.",
        "en": "No norm was found for {count} record(s) — deviation from the norm "
              "was NOT CHECKED for them. The norm comes from `fuel_norm`.",
    },
    "note.empty_tables": {
        "uz": "Quyidagi jadvallarda yozuv yo'q, shuning uchun ular "
              "tekshirilmadi: {tables}.",
        "ru": "В следующих таблицах нет записей, поэтому они не проверялись: "
              "{tables}.",
        "en": "The following tables have no records, so they were not checked: "
              "{tables}.",
    },

    # -------------------------------------------------- Anomaliya izohi
    "expl.no_finding": {
        "uz": "Topilma yo'q.", "ru": "Находок нет.", "en": "No findings."},
    "expl.vehicle": {
        "uz": "{plate} mashinasi", "ru": "машина {plate}", "en": "vehicle {plate}"},
    "expl.driver": {
        "uz": "haydovchi {name}", "ru": "водитель {name}", "en": "driver {name}"},
    "expl.document": {
        "uz": "hujjat {number}", "ru": "документ {number}", "en": "document {number}"},

    "advice.IMPOSSIBLE": {
        "uz": " Bunday qiymat bo'lishi mumkin emas — hujjatni tekshirish kerak.",
        "ru": " Такое значение невозможно — нужно проверить документ.",
        "en": " Such a value is impossible — the document must be checked.",
    },
    "advice.MISMATCH": {
        "uz": " Raqamlar bir-biriga zid — hujjatni tekshirish kerak.",
        "ru": " Цифры противоречат друг другу — нужно проверить документ.",
        "en": " The figures contradict each other — the document must be checked.",
    },
    "advice.OVER_LIMIT": {
        "uz": " Limit oshgan — sababi aniqlanishi kerak.",
        "ru": " Лимит превышен — нужно установить причину.",
        "en": " The limit was exceeded — the reason must be established.",
    },
    "advice.OVER_NORM": {
        "uz": " Normadan oshgan — sababi aniqlanishi kerak.",
        "ru": " Норма превышена — нужно установить причину.",
        "en": " The norm was exceeded — the reason must be established.",
    },
}
