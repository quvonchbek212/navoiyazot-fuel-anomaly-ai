"""Daily fuel/GPS reconciliation over the same completed trip intervals.

No whole-day GPS distance is divided into a differently scoped fuel total.
ATIL queries are bounded, parameterized and read-only; no scheduler or writes.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as day_time, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
import threading
import time
import pytz

from pydantic import BaseModel, ConfigDict, Field

from oil_detection.investigation_queries import select
from oil_detection.queries import OilDataError
from oil_detection.rules import canonical_fuel

ZONE = pytz.timezone('Asia/Tashkent')
MAX_DOCUMENTS = 50
COLLECTION_SECONDS = 90
MAX_WORKERS = 4


# A conflicting document is searched across all closed waybills, not only the
# displayed 50 rows. A row hidden by the limit therefore cannot be double-counted.
COHORT_SQL = """
with cohort as (
 select w.id::text as id,w.waybill_number,w.issue_date,w.status,
        w.vehicle_id::text,w.trip_id::text,w.fuel_type,w.calculation_mode,w.work_mode,
        w.actual_departure_at,w.actual_return_at,w.fuel_at_departure_liters,
        w.fuel_issued_liters,w.fuel_at_return_liters,w.fuel_consumed_liters,
        w.fuel_norm_liters,w.odometer_start_km,w.odometer_end_km,w.motohours_worked,
        v.plate_number
 from waybill w left join transport_vehicle v on v.id=w.vehicle_id
 where w.status in ('CLOSED','RETURNED') and (
   (w.actual_departure_at<%s and w.actual_return_at>%s)
   or (w.issue_date=%s and (w.actual_departure_at is null or w.actual_return_at is null
                          or w.actual_return_at<=w.actual_departure_at)))
), classified as (
 select c.*,case
   when actual_departure_at is null or actual_return_at is null
        or actual_return_at<=actual_departure_at then 'INVALID_WINDOW'
   when actual_departure_at<%s or actual_return_at>%s then 'CROSS_DAY'
   when exists (
     select 1 from waybill other where other.id<>c.id::uuid
       and other.vehicle_id=c.vehicle_id::uuid and other.status in ('CLOSED','RETURNED')
       and ((c.trip_id is not null and other.trip_id=c.trip_id::uuid)
         or (other.actual_departure_at<other.actual_return_at
             and other.actual_departure_at<c.actual_return_at
             and other.actual_return_at>c.actual_departure_at))) then 'OVERLAP'
   else 'ELIGIBLE' end as scope_state
 from cohort c
)
"""


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _float(value):
    return round(float(value), 3) if value is not None else None


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    return value if isinstance(value, datetime) and value.utcoffset() is not None else None


def window(day: date):
    start = ZONE.localize(datetime.combine(day, day_time.min))
    return start, start + timedelta(days=1)


def load(day: date):
    """Four batch reads: exact scope, bounded documents, fuelings and norms."""
    start, end = window(day)
    params = (end, start, day, start, end)
    rows = select(COHORT_SQL + """
      select count(*) as total_documents,
        count(*) filter(where scope_state='ELIGIBLE') as eligible_documents,
        count(*) filter(where scope_state='CROSS_DAY') as cross_day_documents,
        count(*) filter(where scope_state='INVALID_WINDOW') as invalid_window_documents,
        count(*) filter(where scope_state='OVERLAP') as overlapping_documents
      from classified
    """, params)
    scope = rows[0] if rows else {}
    targets = select(COHORT_SQL + """
      select * from classified
      order by (scope_state='ELIGIBLE') desc,actual_departure_at desc nulls last,id
      limit %s
    """, (*params, MAX_DOCUMENTS))
    ids = [r['id'] for r in targets if r.get('scope_state') == 'ELIGIBLE']
    fuelings, norms = defaultdict(list), defaultdict(list)
    source_errors = {}
    def optional_rows(name, query, query_params):
        try:
            return select(query, query_params)
        except OilDataError:
            source_errors[name] = 'UNAVAILABLE'
            return None
    if ids:
        rows = optional_rows('fuelings', """
          with numbered as (
            select f.waybill_id::text,f.fueling_id::text,f.occurred_at,f.quantity,f.fuel_type,
                   f.warehouse_id::text,f.external_station,
                   s.latitude as station_latitude,s.longitude as station_longitude,
                   case when s.id is not null then 'FUEL_WAREHOUSES' end as station_source,
                   row_number() over(partition by f.waybill_id order by f.occurred_at,f.fueling_id) as rn
            from waybill_fueling f
            left join reference_data s on s.id=f.warehouse_id and s.active
              and s.catalog_type='FUEL_WAREHOUSES'
            where f.waybill_id=any(%s::uuid[]))
          select * from numbered where rn<=101 order by waybill_id,rn
        """, (ids,))
        if rows is None:
            fuelings.update({key: None for key in ids})
        for row in rows or []:
            fuelings[row['waybill_id']].append({k: v for k, v in row.items() if k not in ('waybill_id', 'rn')})
        rows = optional_rows('norms', """
          with numbered as (
            select w.id::text as waybill_id,n.id::text,n.fuel_type,n.liters_per100km,
                   n.liters_per_engine_hour,n.tolerance_percent,n.effective_from,n.effective_to,
                   row_number() over(partition by w.id order by n.effective_from desc,n.id) as rn
            from waybill w join fuel_norm n on n.vehicle_id=w.vehicle_id
              and n.effective_from<=(w.actual_departure_at at time zone 'Asia/Tashkent')::date
              and (n.effective_to is null or n.effective_to>=
                   ((w.actual_return_at-interval '1 microsecond') at time zone 'Asia/Tashkent')::date)
            where w.id=any(%s::uuid[]))
          select * from numbered where rn<=31 order by waybill_id,rn
        """, (ids,))
        if rows is None:
            norms.update({key: None for key in ids})
        for row in rows or []:
            norms[row['waybill_id']].append({k: v for k, v in row.items() if k not in ('waybill_id', 'rn')})
    return {'scope': scope, 'targets': targets, 'fuelings': dict(fuelings), 'norms': dict(norms),
            'source_errors': source_errors}


def classify(targets, start, end):
    """Defend interval/identity boundaries even with mocked or changed sources."""
    states = []
    ids = Counter(t.get('id') for t in targets)
    for target in targets:
        departure, returned = _aware(target.get('actual_departure_at')), _aware(target.get('actual_return_at'))
        state = target.get('scope_state', 'ELIGIBLE')
        if not departure or not returned or returned <= departure:
            state = 'INVALID_WINDOW'
        elif departure < start or returned > end:
            state = 'CROSS_DAY'
        elif ids[target.get('id')] != 1 or not target.get('id') or not target.get('vehicle_id'):
            state = 'OVERLAP'
        elif target.get('status') not in ('CLOSED', 'RETURNED'):
            state = 'NOT_COMPLETED'
        states.append(state)
    # Match against all fetched rows, including cross-day and invalid-duration
    # duplicates. SQL additionally compares against rows outside this batch.
    for index, target in enumerate(targets):
        if states[index] != 'ELIGIBLE':
            continue
        departure, returned = _aware(target['actual_departure_at']), _aware(target['actual_return_at'])
        for other_index, other in enumerate(targets):
            if index == other_index or target.get('vehicle_id') != other.get('vehicle_id'):
                continue
            duplicate = target.get('trip_id') and target.get('trip_id') == other.get('trip_id')
            a, b = _aware(other.get('actual_departure_at')), _aware(other.get('actual_return_at'))
            if duplicate or (a and b and a < b and a < returned and b > departure):
                states[index] = 'OVERLAP'
                break
    return states


REASONS = {
    'INVALID_WINDOW': 'Haqiqiy chiqish va qaytish vaqti to‘liq yoki yaroqli emas.',
    'CROSS_DAY': 'Reys boshqa kunga ham o‘tgan; umumiy sarf kunlarga taxminan bo‘linmadi.',
    'OVERLAP': 'Shu transportning boshqa yo‘l varaqasi bilan vaqt yoki reys bog‘lanishi takrorlangan.',
    'NOT_COMPLETED': 'Yo‘l varaqasi yakunlanmagan.',
    'COLLECTION_TIMEOUT': 'Hisob vaqti chegarasida GPS tekshiruvi olinmadi.',
    'GPS_UNAVAILABLE': 'GPS tekshiruvi bajarilmadi.',
    'INCOMPLETE_EVIDENCE': 'GPS qamrovi yoki shu reysga tegishli sarf taqqoslash uchun yetarli emas.',
}


def _block(key, title, text, *, severity='normal', details=None):
    return {'id': key, 'title': title, 'text': text, 'severity': severity, 'details': details or []}


def report(day: date, *, loaded=None, analyzer=None):
    """Reconcile each non-overlapping, day-contained trip independently."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    start, end = window(day)
    data = load(day) if loaded is None else loaded
    targets = data.get('targets', [])[:MAX_DOCUMENTS]
    states = classify(targets, start, end)
    deadline = time.monotonic() + COLLECTION_SECONDS
    abort_lock = threading.Lock()
    abort_error = None
    if analyzer is None:
        from atil_ai_dispetcher import gps_api
        from oil_detection.gps_analysis import analyze_waybill
        if not gps_api.configured():
            abort_error = 'GPS_NOT_CONFIGURED'
        analyzer = analyze_waybill

    def calculate(pair):
        nonlocal abort_error
        target, state = pair
        result = {'waybill_id': target.get('id'), 'waybill_number': target.get('waybill_number'),
                  'vehicle_id': target.get('vehicle_id'), 'plate_number': target.get('plate_number'),
                  'fuel_type': target.get('fuel_type'), 'status': 'UNAVAILABLE', 'reason': None,
                  'gps_analysis': None}
        if state != 'ELIGIBLE':
            return {**result, 'reason': state}
        with abort_lock:
            stopped_error = abort_error
        if stopped_error:
            return {**result, 'reason': 'INCOMPLETE_EVIDENCE',
                    'gps_analysis': {'status': 'UNAVAILABLE', 'error': stopped_error, 'gps': {}, 'comparison': {}}}
        if time.monotonic() >= deadline:
            return {**result, 'reason': 'COLLECTION_TIMEOUT'}
        try:
            gps_report = analyzer(target, data.get('fuelings', {}).get(target['id'], []),
                                  data.get('norms', {}).get(target['id'], []), deadline=deadline)
            error_code = gps_report.get('error')
            if error_code in ('ACCESS_DENIED', 'INVALID_TOKEN', 'GPS_NOT_CONFIGURED', 'NOT_CONFIGURED'):
                with abort_lock:
                    abort_error = abort_error or error_code
            return {**result, 'status': gps_report['status'], 'gps_analysis': gps_report,
                    'reason': None if gps_report.get('comparison', {}).get('comparable') else 'INCOMPLETE_EVIDENCE'}
        except Exception:
            # Exception text may include network or database details.
            return {**result, 'reason': 'GPS_UNAVAILABLE'}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='fuel-gps-day') as pool:
        items = list(pool.map(calculate, zip(targets, states)))
    groups = {}
    for item in items:
        key = (item['vehicle_id'], canonical_fuel(item.get('fuel_type')))
        group = groups.setdefault(key, {'vehicle_id': item['vehicle_id'], 'plate_number': item['plate_number'],
                    'fuel_type': key[1] or None, 'trip_count': 0, 'comparable_trips': 0,
                    '_distance': Decimal(0), '_consumed': Decimal(0), '_stops': [], '_movement': [], '_observed_distance': [],
                    '_observed_sources': set(), '_partial': False, 'details': [], 'status': 'UNAVAILABLE'})
        group['trip_count'] += 1
        analysis = item.get('gps_analysis') or {}
        group['_partial'] = group['_partial'] or analysis.get('status') != 'COMPLETE'
        comparison = analysis.get('comparison', {})
        distance = _number(comparison.get('gps_distance_km'))
        consumed = _number(comparison.get('consumed_liters'))
        gps_values = analysis.get('gps', {})
        observed_distance = _number(gps_values.get('observed_distance_km'))
        if observed_distance is not None and analysis.get('status') != 'UNAVAILABLE':
            group['_observed_distance'].append(observed_distance)
            if gps_values.get('distance_source'):
                group['_observed_sources'].add(gps_values['distance_source'])
        for source_key, target_key in (('observed_stop_minutes', '_stops'), ('observed_moving_minutes', '_movement')):
            observation = _number(gps_values.get(source_key))
            if observation is not None and analysis.get('status') != 'UNAVAILABLE':
                group[target_key].append(observation)
        comparable = (comparison.get('comparable') is True and distance is not None and distance > 0
                      and consumed is not None and gps_values.get('complete') is True
                      and analysis.get('status') != 'UNAVAILABLE')
        name = item.get('waybill_number') or 'Raqami ko‘rsatilmagan yo‘l varaqasi'
        if comparable:
            group['_distance'] += distance
            group['_consumed'] += consumed
            group['comparable_trips'] += 1
            group['details'].append(f'{name}: ayni reys uchun GPS masofasi {_float(distance)} km, qayd etilgan sarf {_float(consumed)} litr.')
            expected = _number(comparison.get('expected_liters'))
            excess = _number(comparison.get('excess_liters'))
            if expected is not None:
                group['details'][-1] += f' Shu GPS masofasi uchun norma {_float(expected)} litr.'
                if excess is not None and excess > 0:
                    group['details'][-1] += f' Normadan ortiqcha qayd etilgan sarf {_float(excess)} litr; sababini tekshirish kerak.'
            else:
                group['details'][-1] += ' GPS bo‘yicha normaga solishtirish tasdiqlanmagan.'
        else:
            group['details'].append(f"{name}: {REASONS.get(item.get('reason'), REASONS['INCOMPLETE_EVIDENCE'])}")
    vehicles = []
    for group in groups.values():
        distance, consumed = group.pop('_distance'), group.pop('_consumed')
        stops, movement = group.pop('_stops'), group.pop('_movement')
        observed_distance = group.pop('_observed_distance')
        observed_sources = group.pop('_observed_sources')
        partial = group.pop('_partial')
        valid = group['comparable_trips'] > 0
        group.update(gps_distance_km=_float(distance) if valid else None,
                     consumed_liters=_float(consumed) if valid else None,
                     liters_per100km=_float(consumed/distance*100) if valid and distance > 0 else None,
                     observed_stop_minutes=_float(sum(stops)) if stops else None,
                     observed_moving_minutes=_float(sum(movement)) if movement else None,
                     observed_gps_distance_km=_float(sum(observed_distance)) if observed_distance else None,
                     observed_distance_sources=sorted(observed_sources),
                     status='COMPLETE' if group['comparable_trips'] == group['trip_count'] and not partial else 'PARTIAL' if valid else 'UNAVAILABLE')
        vehicles.append(group)
    vehicles.sort(key=lambda v: (str(v['plate_number'] or ''), str(v['fuel_type'] or '')))
    scope = {k: int(data.get('scope', {}).get(k, 0) or 0) for k in (
        'total_documents', 'eligible_documents', 'cross_day_documents', 'invalid_window_documents', 'overlapping_documents')}
    if not data.get('scope'):
        scope.update(total_documents=len(data.get('targets', [])), eligible_documents=states.count('ELIGIBLE'),
                     cross_day_documents=states.count('CROSS_DAY'), invalid_window_documents=states.count('INVALID_WINDOW'),
                     overlapping_documents=states.count('OVERLAP'))
    scope.update(returned=len(items), truncated=scope['total_documents'] > len(items))
    matched = [v for v in vehicles if v['comparable_trips']]
    fuel_types = {v['fuel_type'] for v in matched}
    liters = sum((_number(v['consumed_liters']) for v in matched), Decimal(0)) if matched else None
    kilometers = sum((_number(v['gps_distance_km']) for v in matched), Decimal(0)) if matched else None
    comparable_count = sum(v['comparable_trips'] for v in vehicles)
    summary = {'vehicles': len({i['vehicle_id'] for i in items if i['vehicle_id']}),
               'comparable_trips': comparable_count, 'unavailable_trips': len(items)-comparable_count,
               'matched_gps_distance_km': _float(kilometers), 'matched_consumed_liters': _float(liters),
               'liters_per100km': _float(liters/kilometers*100) if kilometers and len(fuel_types) == 1 and None not in fuel_types else None,
               'fuel_types': sorted(f for f in fuel_types if f)}
    available = any((i.get('gps_analysis') or {}).get('status') != 'UNAVAILABLE' for i in items if i.get('gps_analysis'))
    complete = (bool(items) and not scope['truncated'] and comparable_count == len(items)
                and not data.get('source_errors') and all(i['status'] == 'COMPLETE' for i in items))
    status = 'COMPLETE' if complete else 'PARTIAL' if available else 'UNAVAILABLE'
    gps_failures = Counter()
    for item in items:
        error = (item.get('gps_analysis') or {}).get('error')
        if error:
            error = {'GPS_NOT_CONFIGURED': 'NOT_CONFIGURED', 'GPS_COLLECTION_TIMEOUT': 'PENDING_TIMEOUT'}.get(error, error)
            category = error if error in {'ACCESS_DENIED', 'INVALID_TOKEN', 'NOT_CONFIGURED', 'CONNECTION_FAILED', 'PENDING_TIMEOUT'} else 'GPS_UNAVAILABLE'
            gps_failures[category] += 1
    blocks = [_block('daily_scope', 'Kunlik GPS va yoqilg‘i xulosasi',
        f"{day.strftime('%d.%m.%Y')} uchun {scope['total_documents']} ta yakunlangan hujjat doirasi aniqlandi; {len(items)} tasi tekshirildi. "
        f"{comparable_count} ta reysda GPS masofasi va qayd etilgan sarf aynan bir vaqt oralig‘ida solishtirildi. "
        'Bu hisob kun ichida to‘liq tugagan reyslar uchun; avtoparkning butun kunlik sarfi emas.',
        severity='normal' if complete else 'caution')]
    if gps_failures:
        labels = {
            'ACCESS_DENIED': 'GPS API kirishga ruxsat bermadi. Token muddati va transportga kirish huquqini tekshirish kerak.',
            'INVALID_TOKEN': 'GPS API tokeni noto‘g‘ri shaklda (bo‘sh joy yoki nojo‘ya belgi bor). .env sozlamasini tekshirish kerak.',
            'NOT_CONFIGURED': 'GPS ulanishi sozlanmagan.',
            'CONNECTION_FAILED': 'GPS xizmatiga ulanib bo‘lmadi. Ulanishni qayta tekshirish kerak.',
            'PENDING_TIMEOUT': 'GPS tarixi belgilangan kutish vaqtida tayyor bo‘lmadi.',
            'GPS_UNAVAILABLE': 'Reys uchun GPS ma’lumoti olinmadi. Reys vaqti va GPS manbasini tekshirish kerak.',
        }
        blocks.append(_block('gps_connection', 'GPS ma’lumoti nega olinmadi?',
            'Quyidagi reyslarda GPS asosidagi sarf noma’lum; ular nol sarf yoki ishlamagan transport deb hisoblanmadi.',
            details=[f'{count} ta reys: {labels[code]}' for code, count in sorted(gps_failures.items())], severity='attention'))
    if matched:
        text = f"Mos davrli reyslarda jami {summary['matched_gps_distance_km']} km GPS masofasi va {summary['matched_consumed_liters']} litr qayd etilgan sarf bor. "
        if summary['liters_per100km'] is not None:
            text += f"Shu reyslar yig‘indisi bo‘yicha 100 km sarf {summary['liters_per100km']} litr. "
        else:
            text += 'Turli yoqilg‘i turlari bitta 100 km sarf ko‘rsatkichiga aralashtirilmadi. '
        text += 'Quyilgan yoqilg‘i sarf sifatida qo‘shilmadi.'
    else:
        text = 'Bir xil reys davri uchun taqqoslanadigan GPS masofasi va ishonchli sarf juftligi topilmadi. Sarf noma’lum; nol deb hisoblanmadi.'
    blocks.append(_block('daily_consumption', 'Masofa va sarf bir xil davr uchun', text, severity='normal' if matched else 'caution'))
    details = []
    for v in vehicles:
        name = v['plate_number'] or 'Transport raqami ko‘rsatilmagan'
        fuel = f" ({v['fuel_type']})" if v['fuel_type'] else ''
        if v['comparable_trips']:
            detail = f"{name}{fuel}: {v['comparable_trips']} ta mos davrli reys, {v['gps_distance_km']} km, {v['consumed_liters']} litr; 100 km uchun {v['liters_per100km']} litr."
            if v['comparable_trips'] < v['trip_count']:
                detail += ' Boshqa hujjatlar umumiy sarf nisbatiga qo‘shilmadi.'
        else:
            detail = f'{name}{fuel}: GPS bo‘yicha sarf nisbati noma’lum.'
        if v['observed_gps_distance_km'] is not None:
            source = 'GPS nuqtalaridan taxminiy hisoblangan masofa' if 'GPS_POINTS' in v['observed_distance_sources'] else 'GPS kuzatgan masofa'
            detail += f" Tanlangan reyslarda {source} {v['observed_gps_distance_km']} km; to‘liq bo‘lmagan kuzatuv sarf nisbatiga qo‘shilmadi."
        if v['observed_stop_minutes'] is not None:
            detail += f" Kuzatuvdagi to‘xtash {v['observed_stop_minutes']} daqiqa."
        if v['observed_moving_minutes'] is not None:
            detail += f" Kuzatuvdagi harakat {v['observed_moving_minutes']} daqiqa."
        details.append(detail + ' ' + ' '.join(v['details']))
    blocks.append(_block('vehicles', 'Har bir transport bo‘yicha',
        f"{summary['vehicles']} ta transport bo‘yicha natijalar quyida. Har xil yoqilg‘i turi alohida ko‘rsatiladi." if vehicles else 'Tanlangan kun uchun tekshiriladigan hujjat topilmadi.',
        details=details))
    excluded = (f"Boshqa kunga o‘tgan {scope['cross_day_documents']} ta, vaqti yaroqsiz yoki yetishmagan {scope['invalid_window_documents']} ta, "
                f"vaqti yoki reys bog‘lanishi takrorlangan {scope['overlapping_documents']} ta hujjat sarf nisbatiga qo‘shilmadi. ")
    if scope['truncated']:
        excluded += f"Ro‘yxat {MAX_DOCUMENTS} ta hujjat bilan chegaralangan; qolgan yozuvlar tekshirilmadi. "
    for source, label in (('fuelings', 'Quyish yozuvlari'), ('norms', 'Yoqilg‘i normalari')):
        if source in data.get('source_errors', {}):
            excluded += label + ' olinmadi; shu manba bo‘yicha tekshiruv noma’lum. '
    excluded += 'Qisman GPS masofasi ortiqcha sarf hukmiga asos bo‘lmaydi. GPS to‘xtashi dvigatel ishlaganini yoki bakdan yoqilg‘i kamayganini isbotlamaydi.'
    blocks.append(_block('daily_limits', 'Hisobning chegaralari', excluded, severity='caution'))
    return {'day': day.isoformat(), 'timezone': 'Asia/Tashkent', 'generated_at': datetime.now(ZONE),
            'period': {'start': start, 'end': end}, 'status': status, 'scope': scope, 'summary': summary,
            'vehicles': vehicles, 'items': items, 'source_errors': data.get('source_errors', {}), 'gps_failures': dict(gps_failures),
            'narrative': {'title': 'Kunlik GPS va yoqilg‘i tahlili', 'blocks': blocks},
            'analysis': {'status': 'CALCULATED', 'source': 'calculated', 'text': 'Xulosa mavjud dalillardan hisoblandi. AI izohi hali olinmagan.'}}


class DailyExplanation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=20, max_length=850)


async def enrich(report):
    """An optional short explanation; calculated facts survive a model outage."""
    facts = {k: report[k] for k in ('status', 'scope', 'summary', 'source_errors')}
    facts['gps_failures'] = report.get('gps_failures', {})
    prompt = ('Siz yoqilg‘i nazoratchisiga o‘zbekcha sodda izoh yozasiz. Quyidagi hisoblangan faktlarga tayangan '
              'uchta qisqa jumla yozing, jami yuz yigirma so‘zdan oshmasin. Son yoki foiz kiritmang, hisoblamang. '
              'Yangi sabab, norma, tejash, aybdorlik, o‘g‘irlik, sizish yoki dvigatel holatini to‘qimang. '
              'Bu faqat bir kun ichida tugagan, vaqt oralig‘i mos reyslar hisobi. Qisman GPS va yetishmagan '
              'ma’lumotni ishonchli sarf sifatida talqin qilmang. Solishtirilgan reys bo‘lmasa tekshirish zarurligini '
              'ayting, muammo yo‘q demang. Shaxsiy ma’lumot yoki koordinata yo‘q. Faqat {"text":"..."} JSON. Faktlar: '
              + json.dumps(facts, ensure_ascii=False))
    try:
        from ollama_client import ask_llm
        raw = await asyncio.wait_for(ask_llm(prompt, {
            'timeout': 30, 'response_json_schema': DailyExplanation.model_json_schema(),
            'think': False, 'enable_thinking': False,
            'options': {'temperature': .1, 'num_predict': 250},
        }), timeout=30)
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
        answer = DailyExplanation.model_validate_json(clean).text
        if (len(answer.split()) > 120 or re.search(r'[0-9<>%]|o‘g‘ir|o\'g\'ir|aybdor|sizish|teja|nosoz|firib|dvigatel.{0,15}ishla', answer, re.I)):
            raise ValueError('Unsupported explanation')
        report['analysis'] = {'status': 'COMPLETE', 'source': 'llm', 'text': answer}
    except Exception:
        report['analysis'] = {'status': 'UNAVAILABLE', 'source': 'calculated',
            'text': 'AI izohi olinmadi. Quyida mavjud ma’lumotlardan hisoblangan tushuntirish saqlandi.'}
    return report
