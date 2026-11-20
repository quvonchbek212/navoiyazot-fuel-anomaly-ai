# Yoqilg'i dalillarini tekshiruvchi AI agent

Agent bitta yo'l varaqasini tekshiradi. U savol va olingan dalilga qarab
keyingi vositalarni tanlaydi, ularning natijasini ko'rib tekshiruvni davom
ettiradi, so'ng kuzatuvlar, ehtimoliy sabablar, qarshi dalillar va aniq keyingi
qadamlarni qaytaradi. Sarfni prognoz qiladigan yoki o'rganadigan model yo'q.

## Chaqirish

Mavjud FastAPI ilovasi va uning HTTP Basic avtorizatsiyasi ishlatiladi.
Swagger'da `Yoqilg'i anomaliyasi` bo'limini oching.

```http
POST /oil-detection/investigate
Content-Type: application/json
```

```json
{
  "waybill_id": "00000000-0000-0000-0000-000000000001",
  "lang": "uz",
  "question": "Shu topshiriqdagi bir xil mashinalar bilan solishtir. Yuk va qaytishdagi bo'sh qatnov sarfni izohlaydimi?",
  "comparison_days": 14
}
```

UUID misol uchun berilgan: uni haqiqiy `waybill.id` bilan almashtiring.
`scan` javobidagi `waybill:<id>` anomaliyasidan `<id>` qismini olish mumkin.
`fuel_record` ID sini bu endpointga yubormang.

`comparison_days` — hujjat sanasidan orqaga qidiruv oynasi (1–90 kun),
sarf chegarasi emas. `lang`: `uz`, `ru`, `en`. Bir so'rov bitta mustaqil
tekshiruv; oldingi suhbat yoki natija bazaga saqlanmaydi.

## Agent qanday ishlaydi

1. Yo'l varaqasi, transport va ish topshiriqlaridan boshlang'ich `E0` dalilini oladi.
2. Ishchi repositoryda `gps_coverage` avtomatik bir marta bajariladi. GPS
   ulanmagan yoki dalil yetishmagan bo‘lsa ham bu holat ochiq qaytariladi;
   tekshiruv LLMning vosita tanlashiga bog‘liq emas.
3. LLM keyingi qadam uchun ko'pi bilan uchta vositani tanlaydi.
4. Backend ruxsat etilgan, parametrli o'qish so'rovlarini bajaradi.
5. Natijalar yangi dalil ID lari bilan modelga beriladi; model keyingi tekshiruvni tanlaydi.
6. Yakuniy javob sxemasi, dalil havolalari, sonlar va ayrim sabab-manba bog'lanishlari tekshiriladi.

Balans/quyish va o'xshash qatnov qidiruvi tugatishdan oldin bajarilishi shart.
Oldindan bajarilgan GPS tekshiruvi qayta chaqirilmaydi; qolgan yo'nalishlarni
model tanlaydi. Qadamlar soni chegaralangan. Takroriy
vosita, noma'lum vosita yoki model tomonidan SQL/filtr berish qo'llanmaydi.

| Vosita | Nima tekshiriladi |
|---|---|
| `fuel_ledger` | Bak balansi, hujjatdagi quyish va quyish registri, ehtimoliy nusxa yozuvlar |
| `peer_trips` | Shu filial, shu topshiriq yoki marshrutdagi boshqa bir xil marka/model qatnovlari |
| `vehicle_history` | Shu mashinaning avvalgi qatnovlari va sharoit farqlari |
| `driver_history` | Shu haydovchining boshqa qatnovlari va mashinalar/sharoit farqlari |
| `norms` | Hujjat sanasida amal qilgan, yoqilg'i turi mos normalar |
| `gps_coverage` | Haqiqiy reys vaqtidagi GPS masofasi, qamrov, sarf nisbati, kuzatilgan harakat/to‘xtash va quyish vaqtidagi joylashuv |
| `repairs` | Tekshiruv davriga aloqador ta'mir yozuvlari |

## Adolatli taqqoslash

Qidiruvdan topilgan qatnov avtomatik ravishda teng sharoitli deb olinmaydi.
Har nomzodda `matched`, `different`, `unknown` maydonlari bor. Marka, model,
dvigatel quvvati, transport turi, marshrut, yoqilg'i, hisob/ish rejimi,
tirkama, yo'nalish, yukning manbasi va miqdori, qatnov soni, kun va masofa
tekshiriladi. Boshlang'ich versiya aniq moslikdan foydalanadi; yuk yoki
masofa uchun taxminiy tolerans kiritilmagan.

`comparable_on_recorded_conditions=true` bo'lgandagina hujjatlardagi
100 km sarflari farqi hisoblanadi. Bu moslik ham ob-havo, tirbandlik yoki
haydovchi sababini isbotlamaydi. Boshqa kundagi tarixiy yozuvlar kontekst
sifatida qoladi; teng ish sharoiti deb ko'rsatilmaydi.

- Noma'lum yuk nol/yuksiz deb olinmaydi. Manbalar ziddiyatli yoki topshiriqlar
  kesilgan bo'lsa yuk bo'yicha xulosa cheklanadi.
- Borish/qaytish tonnalari va topshiriq og'irliklari o'z kesimida saqlanadi.
  Bir nechta topshiriq og'irligi bitta vaqtdagi yuk deb yig'ilmaydi.
- Yo'lovchi transportida `passenger_count` kerak: nol tonna yukning o'zi
  yo'lovchisiz qatnovni tasdiqlamaydi.
- Harakatdagi/yopilmagan hujjat yakuniy sarf taqqoslashiga kirmaydi.
- Manfiy qiymat, orqaga ketgan spidometr yoki balans ziddiyati bo'lsa sarf
  tezligi taqqoslash uchun ishlatilmaydi. Arifmetika `Decimal` bilan bajariladi.
- Gaz uchun eski `liters` maydonlarining birliklari tasdiqlanmaguncha sarf
  tezligi taqqoslanmaydi, litr/kub metr orasida konvertatsiya qilinmaydi.
- `fuel_record.liters` sarfga qo'shilmaydi. Quyish registri bilan mos yozuvlar
  ehtimoliy nusxa deb ko'rsatiladi, mustaqil tasdiq deb emas.

## Javob

| Maydon | Mazmuni |
|---|---|
| `conclusion.summary` | Dalil havolalari bilan qisqa xulosa |
| `conclusion.observations` | Tekshiruvda ko'rilgan holatlar |
| `conclusion.hypotheses` | Sabab taxminlari; tasdiqlangan sabab yoki ayblov emas |
| `conclusion.counterevidence` | Dastlabki shubhaga qarshi dalillar, topilgan bo'lsa |
| `conclusion.missing_information` | Tekshirishga to'sqinlik qilayotgan bo'shliqlar |
| `conclusion.next_actions` | Nazoratchi uchun aniq tekshiruv tavsiyalari |
| `evidence` | Backend olgan raqamlar, manbalar, cheklovlar va dalil ID lari |
| `steps` | Qisqa tekshiruv maqsadi va bajarilgan vositalar |
| `unvisited_tools` | Ushbu so'rovda ishlatilmagan vositalar |
| `gps_analysis` | Kod hisoblagan GPS natijasi, qamrov cheklovlari va front uchun `narrative.blocks` kartochkalari |

Har matndagi `evidence_ids` ni `evidence[].id` bilan bog'lab ko'rsating.
`needs_review` yoki `insufficient_evidence` — inson ko'rib chiqishi uchun
holat; avtomatik aybdorlik yoki aniq nosozlik hukmi yo'q.

`evidence.state=missing` — shu filtrda dalil topilmadi yoki zarur kontekst yo'q.
`unavailable` — so'rov bajarilmadi; bo'sh jadval degani emas. `truncated=true`
bo'lsa tanlov kesilgan. Har bir qidiruvda ko'pi bilan 30 qatnov/ta'mir/norma,
har varaqada 20 topshiriq, registrda 100 yozuv ko'rsatiladi. LLMga uzun
ro'yxatlarning dastlabki to'rtta elementi va qancha element qisqartirilgani
beriladi; API dalillarida so'rov chegarasigacha barcha o'qilgan yozuvlar qoladi.

GPS to‘xtashi navbat yoki motor yoqilgan holda bekor ishlash deb nomlanmaydi.
Bakdagi kamayish, sizish va o‘g‘irlik GPSdan aniqlanmaydi. Ta'mir bilan
bog'liqlik ham sabab isboti emas.
Statik son/havola tekshiruvi LLM matnining barcha semantik da'volarini
isbotlamaydi; nazoratchi manba dalillarini ko'rishi kerak.

## GPS va sarfning aynan bir davrga tegishliligi

`gps_analysis.py` faqat `CLOSED` yoki `RETURNED` hujjatning vaqt zonasi bor
`actual_departure_at`–`actual_return_at` oralig‘ini oladi. `issue_date` reysning
boshlanish vaqti o‘rniga ishlatilmaydi. Vaqt yetishmasa, tartibi noto‘g‘ri,
kelajakda yoki davr yetti kundan uzun bo‘lsa GPS so‘rovi yuborilmaydi.

Server ATIL tarix tanlovini yaratib, sahifalarini va shu tanlovning `/distance`
javobini oladi. To‘liq masofa uchun quyidagilar birgalikda bajarilishi kerak:

- Tarix sahifalari tugagan, limitga yetilmagan, chiqarib tashlangan yoki
  mahalliy tekshiruvda yaroqsiz topilgan nuqta va aniqlangan signal uzilishi yo‘q.
- Kamida ikkita nuqta bor; birinchi va oxirgi nuqta reys chegaralariga
  ko‘pi bilan 120 soniya yaqin.
- Masofa javobida `complete=true`, `gapCount=0`, `source=GPS_TRACK` va
  `effectiveFrom`/`effectiveTo` aynan so‘ralgan davrga teng.

Shunda hujjat masofasi minus GPS masofasi hisoblanadi. Musbat GPS masofasi
va yaroqli hujjat sarfi mavjud bo‘lsa `litr / GPS km × 100` beriladi.
`MOTOHOURS_ONLY`, `KM_AND_MOTOHOURS` va noma’lum rejimlarda umumiy sarf
kilometrlarga bo‘linmaydi; ruxsat etilgan masofa rejimlari `KM_ONLY`, `KM`,
`DISTANCE`. Yoqilg‘i turi bo‘sh, gazning birligi tasdiqlanmagan yoki hujjatda
arifmetik ziddiyat bo‘lsa ham bu nisbat chiqarilmaydi. To‘liq GPS masofasi nol
bo‘lsa nolga bo‘lish bajarilmaydi.

GPS uchun norma alohida so‘rovda **butun haqiqiy reys davrini** qamrab olishi
kerak; qaytish vaqti chiqarib tashlangan chegara sifatida olinadi. Yoqilg‘i
turi harf registridan tashqari aynan mos bo‘lishi kerak; `DIESEL` va `DIZEL`
taxminan birlashtirilmaydi. Bir-biriga zid norma yoki noma’lum tolerans bo‘lsa
ortiqcha sarf chiqarilmaydi. Oddiy `norms` vositasi hujjat sanasi bo‘yicha
ishlashda davom etadi.

To‘liq qamrov tasdiqlanmasa faqat kuzatilgan masofa yoki GPS nuqtalaridan
taxminiy masofa beriladi. Qisman masofadan sarf nisbati yoki ortiqcha sarf
chiqarilmaydi. Ruxsat rad etilishi va API xatosi bo‘sh tarix yoki nol masofa
deb olinmaydi; bu oqim DB arxiviga yashirin qaytmaydi.

`gps_analysis` quyish qaydi vaqtiga eng yaqin GPS nuqtasini qidiradi; 120
soniyadan uzoq nuqta joylashuv tasdig‘i sifatida olinmaydi. `LOCATION_OBSERVED`
faqat yaqin vaqtda koordinata kuzatilganini bildiradi. Shoxobcha joyi faqat
faol `reference_data` yozuvining `FUEL_WAREHOUSES` katalogidan, haqiqiy
`warehouse_id` bog‘lanishi orqali olinadi. Tashqi shoxobcha uchun ushbu
koordinata ishlatilmaydi. Masofa bo‘lsa to‘g‘ri chiziqli metr ko‘rsatiladi;
radius, «mos/mos emas» hukmi yoki quyilgan litrni GPS bilan tasdiqlash yo‘q.
2026-11-04 bazani o‘qib tekshirishda quyish yozuvlariga bog‘langan yaroqli
shoxobcha koordinatalari topilmadi, shu sabab bu masofa hozir noma’lum qoladi.

GPS kartochkalari o‘zbek tilida va bitta ko‘k natija oynasida chiqadi. LLMga
faqat qisqa raqamlar, vaqtlar, holatlar va cheklovlar beriladi; aniq koordinata,
qurilma IDsi va xom nuqtalar uzatilmaydi. Vakolatli front foydalanuvchisi esa
GPS kartochkasida kuzatilgan joy koordinatasini ko‘rishi mumkin.

## Kunlik GPS va yoqilg‘i xulosasi

```http
GET /oil-detection/gps-daily?day=2026-10-21
```

Mavjud HTTP Basic avtorizatsiyasi talab qilinadi. `day` majburiy va
`Asia/Tashkent` kalendar kunidir. Hisob faqat shu kun ichida boshlangan va
tugagan reyslarga tegishli; qaytish aynan keyingi kun boshida bo‘lishi mumkin.
Boshqa kunga o‘tgan, vaqti yetishmagan yoki bitta transportda vaqt/reys
bog‘lanishi takrorlangan hujjatlar sarf nisbatidan chiqariladi. Takrorlanish
tekshiruvi faqat ekranga chiqarilgan hujjatlar bilan cheklanmaydi.

Ko‘pi bilan 50 hujjat olinadi; GPS yig‘ish to‘rtta parallel ishchi va 90 soniya
umumiy budjet bilan bajariladi. Har bir yaroqli reys alohida tekshiriladi,
so‘ng shu reyslarning kilometri va sarfi transport/yoqilg‘i turi bo‘yicha
yig‘iladi. Turli yoqilg‘i turlari bitta 100 km sarf nisbatiga aralashtirilmaydi.
Bu butun sutka GPS masofasiga boshqa davrdagi yoqilg‘ini bo‘lish emas.

Javobdagi `scope` hisob qamrovini, `summary` taqqoslangan reyslar yig‘indisini,
`vehicles` transport natijalarini, `items` reys dalillarini, `narrative.blocks`
front uchun matnli kartochkalarni beradi. `COMPLETE`, `PARTIAL`, `UNAVAILABLE`
holatlari va manba xatolari ochiq qaytariladi. Bo‘sh yoki olinmagan ma’lumot
nol deb hisoblanmaydi. Quyish/norma so‘rovi ishlamasa qolgan GPS dalili saqlanadi.

Kunlik xulosaning LLM izohi ixtiyoriy: model ishlamasa yoki izoh tekshiruvdan
o‘tmasa `analysis.status=UNAVAILABLE`, `analysis.source=calculated` bo‘ladi,
hisoblangan kartochkalar saqlanadi. Bu zaxira faqat `/gps-daily` uchun;
`/investigate` LLM ishlamasa 503 qaytarishda davom etadi.

## Bazani o'zgartirmaslik

Agentning DB yozish vositasi yo'q. SQL oldindan kodda belgilangan va
`ensure_read_only` orqali tekshiriladi. Yozish buyruqlari ulanish ochilishidan
oldin rad etiladi. Har so'rov `SET TRANSACTION READ ONLY` bilan bajariladi.
`statement_timeout` va vaqt zonasi faqat shu tranzaksiya uchun `SET LOCAL`
bilan o'rnatiladi; baza sozlamalariga doimiy o'zgarish kiritilmaydi.
Ulanish qaytarilganda umumiy pool tranzaksiyani rollback qiladi.

Migratsiya, jadval yaratish, ma'lumot yangilash/o'chirish yoki agent natijasini
bazaga saqlash yo'q. SQL qiymatlari parametrli. Modelga DB paroli, ulanish
manzili, shaxsiy izohlar yoki GPS xom payloadi yuborilmaydi.

## Operatsion chegaralar va xatolar

Mavjud sozlangan LLM klienti ishlatiladi. Yangi model yoki dependency kerak emas.
Agent vLLM uchun so'rov darajasida `chat_template_kwargs.enable_thinking=false`
beradi ([Gemma 4 vLLM qo'llanmasi](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)).
JSON kontrakti generatsiya sxemasida ham, prompt ichida ham ko'rsatiladi.
Qisqa xulosada eng muhim kuzatuv, gipoteza, qarshi dalil, bo'shliq va tavsiya
tanlanadi; to'liq raqamli dalillar `evidence` da qoladi.

```ini
OIL_AGENT_MAX_ROUNDS=3
OIL_AGENT_LLM_TIMEOUT_SECONDS=90
OIL_AGENT_FINAL_TIMEOUT_SECONDS=180
OIL_AGENT_TOTAL_TIMEOUT_SECONDS=300
```

Bu qiymatlar `.env` da bo'lmasa yuqoridagi sukut qiymatlar ishlaydi. Har bir
dalil SQL so'rovi uchun 10 soniya chegara bor. Parametrlar resurs chegaralari,
yoqilg'i meyori emas.

- `422`: UUID, til, davr yoki so'rov shakli yaroqsiz.
- `404`: yo'l varaqasi topilmadi.
- `503`: boshlang'ich baza o'qilishi, LLM, JSON/dalil tekshiruvi yoki umumiy vaqt chegarasi bajarilmadi.
- Qo'shimcha manba ishlamasa uning dalili `unavailable` bo'ladi; model bunga
  mos cheklangan xulosa berishi mumkin.

`/investigate` da LLM ishlamasa tayyor shablon AI xulosasi sifatida qaytarilmaydi.
GPS tarixini yig‘ish budjeti 45 soniyagacha, masofa so‘rovi 8 soniyagacha;
agentdagi GPS bosqichi umumiy tekshiruv muddatidan tashqariga chiqmaydi.
Har reysda ko‘pi bilan 100 quyish qaydi tekshiriladi, 20 to‘xtash tafsiloti
ko‘rsatiladi; kesilgan ro‘yxatlar ochiq belgilanadi.

## Test

```powershell
python -m pytest tests/test_oil_investigation.py tests/test_oil_detection_rules.py tests/test_llm_only_analysis.py -q -p no:cacheprovider
python -m pytest tests/test_oil_gps_analysis.py tests/test_oil_gps_evidence.py tests/test_oil_gps_daily.py -q -p no:cacheprovider
```

Testlar soxta repository va modeldan foydalanadi. DB yozish amallari hech
qachon jonli bazada sinab ko'rilmaydi; bloklash lokal soxta ulanish bilan tekshiriladi.
