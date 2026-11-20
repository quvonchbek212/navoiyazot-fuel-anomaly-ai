# Yoqilg'i tekshiruvi (`/oil-detection`)

## Brauzerdagi ish oynasi

Loyiha ildizidan ishga tushirish:

```powershell
.\venv\Scripts\python.exe -m oil_detection --host 127.0.0.1 --port 8031
```

Front: `http://127.0.0.1:8031/oil-detection/`. Mavjud `.env` ichidagi
`API_USERNAME` / `API_PASSWORD` bilan kiriladi. Login ma’lumotlari brauzer
omboriga yozilmaydi. Asosiy `main:app` ham shu front va APIlarni beradi.

- Sana oralig‘i bo‘yicha umumiy AI tahlili, hisob qamrovi va topilma kartochkalari.
- Shu davrdagi yakunlangan yo‘l varaqalarini hujjat yoki transport raqami bilan
  qidirish. Eng yangi 100 ta natija ko‘rsatiladi, jami son va cheklov ochiq aytiladi.
- Yo‘l varaqasini tanlab savol berish yoki topilma kartochkasidan reysni tanlash.
- Bitta ko‘k ish oynasida alohida kartochkalar: AI xulosasi, kuzatuvlar,
  ehtimoliy sabablar, qarshi dalillar, yetishmayotgan ma’lumotlar va keyingi
  tekshiruvlar. Dalil havolalari ochiladi.
- Bitta reys tekshiruvida GPS masofasi, hujjatdagi sarf, kuzatilgan to‘xtashlar
  va quyish vaqtidagi joylashuv shu natija oynasida tushuntiriladi.
- «Kunlik GPS va yoqilg‘i xulosasi»: Toshkent kunini tanlab, shu kun ichida
  boshlangan va tugagan reyslarni birgalikda tekshirish.
- Kutish va xato holatlari, chop etish, telefon ekraniga mos ko‘rinish.

Bu front so‘rov bo‘yicha ishlaydi; avtomatik jadval qo‘shilmagan. Umumiy tahlil
yoki reys agentining AI xizmati mavjud bo‘lmasa xato ko‘rsatiladi va avvalgi
natija saqlanadi. Yangi kunlik GPS hisobi esa LLM ishlamasa ham hisoblangan
kartochkalarni ko‘rsatadi va AI izohi olinmaganini bildiradi.
Bazaga yozish yoki tayinlash amallari yo‘q.

GPS va yoqilg‘i qo‘shimchasidan oldingi front tekshiruvi (2026-11-04):
tegishli backend sinovlari **110 passed**. Jonli baza
qidiruvi, umumiy AI tahlili (14 s) va bitta reys agenti (55 s) HTTP 200 qaytardi.
Sinov reysida dalil yetishmagani `insufficient_evidence` bilan ochiq bildirildi.
Brauzerda kirish, haqiqiy umumiy tahlil/qidiruv, saqlangan haqiqiy agent javobini
ko‘rsatish, dalil havolalari, HTML escape, chiqish paytidagi kechikkan javob va
390 px ekran tekshirildi. Dalillar: `.codex_run/oil-front-live.json` va
`.codex_run/blue-fronts-browser-check.json`.

**Kim ortiqcha sarflayapti va qaysi hujjatni tekshirish kerak.**

`GET /oil-detection/scan` — umumiy hisobot.

`POST /oil-detection/investigate` — reys bo'yicha **dalil izlaydigan AI agent**:
LLM keyingi tekshiruvni olingan dalillarga qarab tanlaydi. Yukli/yuksiz holat,
bir xil mashinalarning qatnovlari, quyishlar, tarix, norma, GPS masofasi va
ta'mir yozuvlari uchun vositalar bor. Sarfni o'rganuvchi model ishlatilmaydi.
[API va ishlash tartibi](INVESTIGATION.md).

`GET /oil-detection/gps-daily?day=2026-10-21` — kunlik GPS va yoqilg‘i
solishtiruvi. Mavjud HTTP Basic avtorizatsiyasi talab qilinadi; `day` majburiy.

```
GET /oil-detection/scan?date_from=2026-08-01&date_to=2026-08-31
```

Sanalar majburiy. "Oxirgi 30 kun" degan sukut qo'yilmagan — u ham o'ylab
topilgan qiymat bo'lardi.

| Bo'lim | Savol |
|---|---|
| `vehicles` | qaysi **mashina** |
| `drivers` | qaysi **haydovchi** |
| `anomalies` | o'sha raqam **qaysi hujjatdan** chiqqani |

## GPS yoqilg‘i tekshiruviga nima qo‘shadi

1. Yakunlangan yo‘l varaqasining **haqiqiy chiqish–qaytish oralig‘i** olinadi.
   GPS tarixi va `/history-selections/{id}/distance` aynan shu vaqt uchun
   so‘raladi. Hujjatdagi spidometr masofasi bilan GPS masofasi farqi ko‘rsatiladi.
2. Qamrov to‘liq tasdiqlansa, shu reysning hujjatdagi sarfi GPS kilometriga
   bo‘linadi: `qayd etilgan litr / GPS km × 100`. Quyilgan miqdor sarfga
   qo‘shilmaydi; natija bak datchigi o‘lchovi sifatida ko‘rsatilmaydi.
3. Yoqilg‘i turi mos va butun reys davrida amal qiladigan yagona `fuel_norm`
   topilsa norma bo‘yicha hisob beriladi. Ortiqcha sarf uchun bazadagi
   `tolerance_percent` ham kerak; taxminiy norma yoki tolerans qo‘yilmaydi.
4. GPSdagi kuzatilgan harakat/to‘xtash daqiqalari va signal uzilishlari
   ko‘rsatiladi. To‘xtash dvigatel ishlaganini yoki yoqilg‘i yoqilganini isbotlamaydi.
5. Quyish yozuvi vaqtiga eng yaqin GPS nuqtasi tekshiriladi. Faqat 120 soniya
   ichidagi nuqta joylashuv kuzatuvi hisoblanadi. Haqiqiy shoxobcha koordinatasi
   bo‘lsa ungacha to‘g‘ri chiziqli masofa beriladi; bu quyish tasdig‘i emas.

**Sifat sharti:** tarix sahifalari to‘liq, yo‘qolgan/chiqarib tashlangan nuqtalar
va signal uzilishlari yo‘q, reys bosh-oxiriga 120 soniya ichida nuqtalar bor,
masofa javobining davri aynan mos, manbasi `GPS_TRACK` bo‘lishi kerak. Shartlar
bajarilmasa faqat kuzatilgan yoki nuqtalardan taxminiy masofa ko‘rsatiladi;
undan 100 km sarf va ortiqcha sarf hisoblanmaydi. GPS nol masofa qaytarsa ham
unga bo‘lish bajarilmaydi. Noma’lum qiymat nolga almashtirilmaydi.

GPSga nisbatan sarf faqat masofa rejimida (`KM_ONLY`, moslik uchun `KM` yoki
`DISTANCE`) hisoblanadi. `MOTOHOURS_ONLY`, `KM_AND_MOTOHOURS` va noma’lum rejim
hisobga kirmaydi. Yoqilg‘i turi bo‘sh, gaz birligi tasdiqlanmagan yoki hujjatda
manfiy qiymat/balans ziddiyati bo‘lsa ham sarf nisbati chiqarilmaydi.

Kunlik hisob butun avtoparkning sutkalik sarfi emas: faqat tanlangan Toshkent
kuni ichida tugagan, vaqti takrorlanmagan reyslar yig‘indisi. Boshqa kunga
o‘tgan, vaqt yetishmagan, bir transportda ustma-ust tushgan yoki bir reysga
takror bog‘langan hujjatlar alohida tushuntiriladi. Ko‘pi bilan 50 hujjat
tekshiriladi; kesilgan ro‘yxat ochiq ko‘rsatiladi. Turli yoqilg‘i turlari bitta
100 km sarf ko‘rsatkichiga aralashtirilmaydi.

2026-11-04 dagi faqat o‘qish bilan baza tekshiruvida quyish yozuvlariga
bog‘langan yaroqli shoxobcha koordinatalari topilmadi. Shuning uchun hozir
GPSdagi joylashuvni ko‘rsatish mumkin bo‘lsa ham shoxobchaga masofa noma’lum
qoladi.

## Asosiy tamoyil: kodda meyor yo'q

Nima bilan solishtirish kerakligini **baza** aytadi:

```
fuel_norm    liters_per100km          yuradigan transport uchun
             liters_per_engine_hour   kran, ekskavator uchun
             tolerance_percent        ruxsat etilgan chetlanish
             effective_from / to      qaysi davrda amal qiladi

fuel_limit   subject_type   DRIVER | VEHICLE
             window_type    DAY | MONTH
             max_liters     chegara
```

Qolgan qoidalar tenglamaning o'zi — ularga chegara kerak emas:

```
qaytgan > chiqishdagi + quyilgan     →  mumkin emas (quyilgan MA'LUM bo'lsa)
litr < 0                             →  mumkin emas
spidometr_oxiri < spidometr_boshi    →  mumkin emas
chiqish + quyilgan - qaytgan ≠ sarf  →  zid (yo'l qo'yish 0)
```

**Norma belgilanmagan mashinaga hukm chiqarilmaydi.** `NO_NORM_DEFINED` deb
yozib qo'yiladi, xolos — taxminiy tolerans bilan ayblash noto'g'ri bo'lardi.
Nechta yozuv normaga solishtirilgani `summary.checked_against_norm` da,
norma qaysi manbadan olingani `summary.norm_sources` da ko'rinadi.

## Uch xil litr — uchtasi ham o'lchangan

| Maydon | Manba | Ma'nosi |
|---|---|---|
| `unaccounted_liters` | hujjatning o'zi | hisobdan tashqari: balans farqi, hujjatsiz quyish |
| `over_limit_liters` | `fuel_limit` | kunlik/oylik limitdan oshgan |
| `excess_liters` | `fuel_norm` | normadan (tolerans bilan) ortiqcha |

Reyting `unaccounted_liters` dan boshlab saralanadi: normadan ortiqcha
sarflashning texnik sababi bo'lishi mumkin, hujjatda litr yo'qolishining esa yo'q.

**Xavf balli yo'q.** 0-100 shkala o'ylab topilgan bo'lardi; saralash
o'lchangan litr bo'yicha boradi, bu ob'ektiv.

## Belgi turlari (`kind`)

Daraja emas, tasnif — "qanchalik yomon" degan baho qo'yilmaydi:

| Turi | Belgilar |
|---|---|
| `IMPOSSIBLE` | `RETURN_EXCEEDS_AVAILABLE`, `NEGATIVE_VALUE`, `ODOMETER_BACKWARDS` |
| `MISMATCH` | `BALANCE_MISMATCH`, `DB_DEVIATION_MISMATCH`, `SOURCE_LITERS_MISMATCH` |
| `OVER_NORM` | `CONSUMPTION_OVER_NORM` |
| `OVER_LIMIT` | `LIMIT_EXCEEDED` |
| `DATA_GAP` | `NO_NORM_DEFINED`, `DISTANCE_UNKNOWN`, `NO_TRIP_BOUND`, `FUEL_ISSUED_UNKNOWN` |

`DATA_GAP` yolg'iz o'zi yozuvni `anomalies` ro'yxatiga chiqarmaydi — u
topilma emas, lekin `notes` da va reytingda ko'rinadi.

## Sarf qaysi asosda o'lchanadi

`metrics.basis` da ko'rinadi, tartib — ishonch darajasi bo'yicha:

1. `expected` — `fuel_record.expected_fuel_liters`, backend hisoblab qo'ygan;
2. `distance` — `fuel_norm.liters_per100km`;
3. `engine_hour` — `fuel_norm.liters_per_engine_hour` (kran, ekskavator:
   0 km yuradi, lekin turgan joyida yoqilg'i yoqadi);
4. `waybill_norm` — yo'l varaqasidagi norma. **Diqqat:** buni mexanikning
   o'zi yozadi, ya'ni `fuel_norm` bilan bir xil ishonchda emas — shuning
   uchun `summary.norm_sources` da alohida sanaladi.

## Takrorlanishning oldini olish

Bitta reys ham `waybill` ga (mexanik yozadi), ham `fuel_record` ga (ERP
yozadi) tushishi mumkin. Ikkalasini alohida sanash sarf yig'indisini **ikki
baravar** qilib yuborardi va soxta limit buzilishini bergan bo'lardi.

Bog'lash `trip_id` bo'yicha, u bo'lmasa hujjat raqami bo'yicha
(`fuel_record.source_reference` = `waybill.waybill_number`). Guruhda sarf
litri **bir marta** sanaladi — `waybill` ustun turadi, chunki uning
`fuel_consumed_liters` ustuni aynan SARFni bildiradi, `fuel_record.liters`
esa quyish yozuvi ham bo'lishi mumkin.

Yozuvlar o'chirilmaydi: har birining o'z qoidalari baribir tekshiriladi.
Nechta voqea takrorlangani `summary.duplicate_groups` da ko'rinadi.

**Bonus:** ikki manba bir voqeaga turli litr yozgan bo'lsa —
`SOURCE_LITERS_MISMATCH`. Bu ikki MUSTAQIL manbaning bir-birini tekshirishi:
yo'l varaqasini odam to'ldiradi, `fuel_record` ga ERP yozadi. Zid bo'lsa,
biri noto'g'ri.

## Limit davr bo'yicha ishlaydi

Har bir reys alohida normal bo'lishi mumkin, lekin kunlik yoki oylik
yig'indi limitdan oshadi. Shuning uchun bu qoida bitta hujjatda emas,
`window_type` ga qarab kun yoki oy kesimida tekshiriladi.

Yig'indi SQL da emas, Python tomonda hisoblanadi: sarf ikki manbadan
(`fuel_record` va `waybill`) kelishi mumkin.

## Topilma va bo'shliq — ikki xil narsa

| Maydon | Nima aytadi |
|---|---|
| `summary.flag_counts` | nima **NOTO'G'RI** — haqiqiy topilmalar |
| `summary.data_gap_counts` | nima **TEKSHIRILMAGAN** — qaysi ustun bo'sh |

Ikkinchisi shart: bo'shliq topilma emas, shuning uchun faqat bo'shligi bor
yozuv `anomalies` ga kirmaydi. Usiz "topilma yo'q" javobi "muammo yo'q"
bo'lib ko'rinardi. 24.08.2026 misoli: 4 ta topilma, lekin **93 hujjatning
93 tasida ham** `fuel_issued_liters` bo'sh, ya'ni bak balansi umuman
tekshirilmagan.

**"Noma'lum" nol deb hisoblanmaydi.** `fuel_issued_liters` bo'sh bo'lsa u
"quyilmagan" degani emas, "yozilmagan" degani. Shuning uchun balans
hisoblanmaydi va `RETURN_EXCEEDS_AVAILABLE` (haydovchini "hujjatsiz quyish"
da ayblaydigan belgi) qo'yilmaydi — o'rniga `FUEL_ISSUED_UNKNOWN` bo'shlig'i
yoziladi. Xuddi `NO_NORM_DEFINED` kabi: bo'shliq hukm emas.

## Arifmetika va LLM

**Aniqlashni arifmetika qiladi, tahlilni LLM.** LLM ga raqam hisoblatilmaydi —
promptga faqat tayyor faktlar boradi va "yangi raqam o'ylab topma" deb
qat'iy aytiladi. Bo'shliqlar ham yuboriladi, LLM "muammo yo'q" deb xulosa
qilib yubormasligi uchun.

Har bir anomaliyaning `explanation` maydoni **shablon** bilan yoziladi
(LLM'siz) va o'z belgilarini to'liq aytadi. LLM esa butun hisobot bo'yicha
**bitta** tahlil yozadi (`analysis`): umumiy manzara, takrorlanadigan naqsh,
eng katta bo'shliq va tavsiya.

Nima uchun har anomaliyaga alohida emas (24.08.2026 o'lchovi):

```
4 ta anomaliyaga 4 ta chaqiruv  ->  67-86 s
bitta umumiy tahlil             ->  17 s
```

Ollama bitta model uchun so'rovlarni navbat bilan bajaradi, ya'ni
`asyncio.gather` hech narsa tejamasdi. Ammo asosiy sabab tezlik emas:
shablon izohi bitta yozuvni allaqachon tushuntiradi, LLM esa yozuvlar
**orasidagi** bog'lanishni ko'radi — buni shablon hech qachon qila olmaydi.

**`/scan` umumiy tahlili shablonga tushmaydi.** Ollama o'chgan bo'lsa endpoint
**503** qaytaradi va frontend "xatolik yuz berdi, keyinroq urinib
ko'ring" deydi. Uni o'chirish yo'li ham yo'q: `explain` parametri ham,
`OIL_LLM_EXPLAIN` sozlamasi ham olib tashlandi.

Har bir anomaliyaning O'Z `explanation` i esa shablon bilan yoziladi va
LLM ga bog'liq emas — u faktlarni sanaydi.

`/gps-daily` uchun tartib boshqacha: masofa, sarf, qamrov va matnli kartochkalar
kod orqali hisoblanadi. LLM faqat qo‘shimcha qisqa izoh beradi. U ishlamasa
`analysis.status=UNAVAILABLE` bo‘ladi, hisoblangan natijalar saqlanadi.

## Javob tili

`/scan` uchun **query parametr**: `?lang=uz|ru|en` (sukut `uz`). Uning javobidagi **hamma matn**
shu tilda chiqadi — belgi nomi (`flags[].title`) va tafsiloti
(`flags[].detail`), anomaliya izohi, `data_quality.notes` va LLM tahlili.
Transport turi ham: `DUMP_TRUCK` -> "samosval" / "самосвал" / "dump truck".

**Kodlar tarjima qilinmaydi.** `flags[].code`, `flags[].kind`, `kinds[]`,
jadval va ustun nomlari uch tilda ham bir xil: ularni dastur o'qiydi va
til o'zgarganda chaqiruvchining filtri buzilmasligi kerak.

Matnlar `texts.py` da, kalit bo'yicha. Transport turlari u yerda
takrorlanmaydi — `atil_chatbot/core/lang.py` dagi chatbot lug'atidan
olinadi.

Yangi GPS kartochkalari va `/gps-daily` matnlari hozir o‘zbek tilida.

## `.env` da nima bor

Meyor emas, xizmatning o'z ishi:

```ini
OIL_MAX_ROWS=20000          # bir so'rovda o'qiladigan eng ko'p yozuv
OIL_LLM_ANALYZE_TOP=5       # tahlilga nechta yuqori anomaliya kiritilsin
```

`OIL_MAX_ROWS` chegarasiga yetilsa javobning `data_quality.notes` ida ochiq
yoziladi — natija jimgina qirqilib qolmaydi.

## `data_quality` ni albatta ko'ring

`row_counts` — har bir manba jadvalda necha yozuv borligi. Manba bo'sh
bo'lsa "topilma yo'q" degani "muammo yo'q" degani emas, "tekshirishga
ma'lumot yo'q" degani. `notes` da nima tekshirilmagani yozib boriladi.

## Bazaga ta'siri

Faqat `SELECT`. Yozuv amali umuman yo'q; ulanish
`default_transaction_read_only=on` bilan ochiladi va baza foydalanuvchisida
faqat `SELECT` huquqi bor. Har bir so'rovda `limit`, bo'sh jadvalga so'rov
umuman yuborilmaydi, norma hamma mashina uchun bitta so'rovda olinadi (N+1 yo'q).

## Fayllar

```
config.py     faqat operatsion sozlamalar (.env dan) — meyor yo'q
models.py     javob sxemasi — Swagger shundan chiziladi
queries.py    SQL — parametrli, faqat SELECT, 6 ta jadval
rules.py      qoidalar (sof funksiyalar)
detector.py   orkestrator: report(date_from, date_to)
explain.py    shablon izohi + bitta LLM tahlili
router.py     umumiy tahlil, reys agenti va kunlik GPS APIlari
gps_analysis.py  ayni reys davri uchun GPS, sarf va quyish kuzatuvlari
gps_daily.py     kun ichida tugagan reyslarni takrorlamasdan solishtirish
frontend/       bitta ko‘k ish oynasi va natija kartochkalari
```

CLI: `python -m oil_detection.detector 2026-08-01 2026-08-31`

Testlar: `tests/test_oil_detection_rules.py` — baza ham, model ham kerak emas.
