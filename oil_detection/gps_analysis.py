"""Fuel documents compared with GPS for the exact, completed trip window.

GPS measures observed travel, not fuel level, theft or engine-on idling.
All computed rates retain their document numerator and telemetry denominator.
"""
from bisect import bisect_left
from datetime import date, datetime, timedelta
from decimal import Decimal
import time

from atil_ai_dispetcher import config as clock, gps, gps_api, gps_activity, garage
from oil_detection.rules import canonical_fuel, match_fuel_norms

MAX_WINDOW_DAYS = 7
EDGE_SECONDS = 120
MAX_FUELINGS = 100
MAX_NORMS = 30


def aware(value):
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return value if isinstance(value, datetime) and value.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def number(value):
    if value is None or isinstance(value, bool): return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except Exception: return None


def rounded(value):
    return float(round(value, 3)) if value is not None else None


def pair(lat, lon):
    lat, lon = number(lat), number(lon)
    return {'latitude': float(lat), 'longitude': float(lon)} if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180 else None


def norm_for_window(norms, target, start, end):
    if norms is None: return None, ['NORM_SOURCE_UNAVAILABLE']
    if len(norms) > MAX_NORMS: return None, ['NORMS_TRUNCATED']
    first = start.astimezone(clock.TIMEZONE).date()
    last = (end-timedelta(microseconds=1)).astimezone(clock.TIMEZONE).date()
    active = []
    for row in norms:
        try:
            begin = date.fromisoformat(str(row.get('effective_from'))[:10])
            finish = date.fromisoformat(str(row['effective_to'])[:10]) if row.get('effective_to') else None
        except (ValueError, TypeError): continue
        if begin <= first and (finish is None or finish >= last):
            active.append(row)
    selected = []
    for row in match_fuel_norms(active, target.get('fuel_type')):
        rate, tolerance = number(row.get('liters_per100km')), number(row.get('tolerance_percent'))
        if rate is not None and rate > 0 and (tolerance is None or tolerance >= 0):
            selected.append((rate, tolerance))
    policies = set(selected)
    if len(policies) != 1: return None, ['NORM_AMBIGUOUS' if policies else 'NO_DISTANCE_NORM_FOR_WINDOW']
    rate, tolerance = next(iter(policies))
    return {'liters_per100km': rate, 'tolerance_percent': tolerance}, ([] if tolerance is not None else ['NORM_TOLERANCE_UNKNOWN'])


def observed_stops(points, barriers):
    episodes = []
    for a, b in zip(points, points[1:]):
        seconds = (b['time']-a['time']).total_seconds()
        index = bisect_left(barriers, a['time'])
        if seconds > garage.MAX_GAP_SECONDS or (index < len(barriers) and barriers[index] <= b['time']): continue
        if a['speed_kph'] is None or b['speed_kph'] is None or max(a['speed_kph'], b['speed_kph']) > 1 or garage.distance(a, b) > 50: continue
        if episodes and episodes[-1]['to_at'] == a['time'] and garage.distance(episodes[-1], b) <= 50:
            episodes[-1]['to_at'] = b['time']
            episodes[-1]['seconds'] += seconds
        else:
            episodes.append({'from_at': a['time'], 'to_at': b['time'], 'seconds': seconds,
                             'latitude': a['latitude'], 'longitude': a['longitude']})
    return [{**s, 'observed_minutes': round(s['seconds']/60, 2)} for s in episodes]


def fueling_context(fuelings, points, start, end):
    if fuelings is None: return [], ['FUELING_SOURCE_UNAVAILABLE']
    limitations = ['FUELINGS_TRUNCATED'] if len(fuelings) > MAX_FUELINGS else []
    times = [p['time'] for p in points]
    output = []
    for row in fuelings[:MAX_FUELINGS]:
        at = aware(row.get('occurred_at'))
        station = pair(row.get('station_latitude'), row.get('station_longitude')) if row.get('external_station') is not True else None
        item = {'occurred_at': at, 'status': 'TIME_UNKNOWN', 'gps_time': None,
                'time_difference_seconds': None, 'distance_to_station_meters': None,
                'station_coordinates_available': station is not None}
        if at is not None:
            if not start <= at <= end: item['status'] = 'OUTSIDE_TRIP_WINDOW'
            else:
                index = bisect_left(times, at)
                candidates = points[max(0, index-1):index+1]
                point = min(candidates, key=lambda p: abs((p['time']-at).total_seconds())) if candidates else None
                if point is None or abs((point['time']-at).total_seconds()) > EDGE_SECONDS:
                    item['status'] = 'NO_NEARBY_GPS'
                else:
                    item.update(status='LOCATION_OBSERVED', gps_time=point['time'],
                                time_difference_seconds=round(abs((point['time']-at).total_seconds()), 2),
                                latitude=point['latitude'], longitude=point['longitude'])
                    if station: item['distance_to_station_meters'] = round(garage.distance(point, station), 1)
        output.append(item)
    return output, limitations


def analyze_waybill(target, fuelings=None, norms=None, *, deadline=None, api_client_factory=None):
    from oil_detection.investigation_evidence import metrics
    deadline = deadline if deadline is not None else time.monotonic()+55
    start, end = aware(target.get('actual_departure_at')), aware(target.get('actual_return_at'))
    doc = metrics(target)
    comparison = {'document_distance_km': doc['distance_km'] if doc['distance_km'] is not None and doc['distance_km'] >= 0 else None,
                  'gps_distance_km': None, 'difference_km': None, 'distance_comparable': False,
                  'consumed_liters': doc['consumed_liters'], 'liters_per100km': None, 'norm_per100km': None,
                  'expected_liters': None, 'excess_liters': None, 'tolerance_percent': None,
                  'comparable': False, 'reasons': []}
    report = {'status': 'UNAVAILABLE', 'source': 'ATIL_API', 'period': {'start': start, 'end': end},
              'gps': {'distance_km': None, 'observed_distance_km': None, 'distance_source': None,
                      'complete': False, 'points': 0, 'signal_gaps': None, 'local_signal_gaps': None,
                      'api_signal_gaps': None, 'api_history_gap_counts': [], 'observed_stop_minutes': None,
                      'observed_moving_minutes': None, 'last_signal_at': None, 'stops': []},
              'comparison': comparison, 'fuelings': [], 'limitations': ['DOCUMENT_FUEL_NOT_SENSOR_MEASUREMENT',
                  'GPS_STOP_DOES_NOT_PROVE_ENGINE_RUNNING', 'DISTANCE_DIFFERENCE_NOT_FRAUD_PROOF'], 'error': None}
    # Gas quantities and unspecified units never become litres by column name.
    fuel = canonical_fuel(target.get('fuel_type'))
    if 'GAS_QUANTITY_UNIT_UNVERIFIED' in doc['issues'] or not fuel:
        comparison['consumed_liters'] = None
    def finish(code=None):
        if code:
            report['error'] = code
            comparison['reasons'].append(code)
        comparison['reasons'] = list(dict.fromkeys(comparison['reasons']))
        report['narrative'] = narrative(report)
        return report
    if start is None or end is None or start >= end: return finish('ACTUAL_TRIP_TIME_WINDOW_UNKNOWN_OR_INVALID')
    if end > clock.now(): return finish('TRIP_WINDOW_IN_FUTURE')
    if end-start > timedelta(days=MAX_WINDOW_DAYS): return finish('TRIP_WINDOW_TOO_LONG')
    if not target.get('vehicle_id'): return finish('VEHICLE_UNKNOWN')
    if target.get('status') not in ('CLOSED', 'RETURNED'): return finish('TRIP_NOT_COMPLETED')
    if not gps_api.configured(): return finish('GPS_NOT_CONFIGURED')
    remaining = deadline-time.monotonic()
    if remaining <= 0: return finish('GPS_COLLECTION_TIMEOUT')
    try:
        client = (api_client_factory or gps_api.GPSClient)()
    except gps_api.GPSAPIError as exc: return finish(str(exc))
    except Exception: return finish('GPS_CLIENT_UNAVAILABLE')
    distance = None
    try:
        raw = client.history(target['vehicle_id'], start, end, budget_seconds=min(45, remaining))
        history = gps.api_history({'vehicle_id': target['vehicle_id']}, raw, start, end)
        remaining = deadline-time.monotonic()
        if raw.get('selection_id') and remaining > 0:
            try: distance = client.distance(raw['selection_id'], start, end, budget_seconds=min(8, remaining))
            except gps_api.GPSAPIError as exc:
                if str(exc) == 'ACCESS_DENIED': return finish('ACCESS_DENIED')
                report['limitations'].append(str(exc))
    except gps_api.GPSAPIError as exc: return finish(str(exc))
    except Exception: return finish('GPS_HISTORY_UNAVAILABLE')
    finally: client.close()
    measured = gps_activity.activity(history, start, end)
    points, barriers, rejected = garage.normalize_observations(history['points'], start, end)
    stops = observed_stops(points, barriers)
    quality = history['quality']
    pages = quality.get('pages') or []
    # Provider and locally detected gaps have different definitions. Preserve
    # both; neither summing nor choosing the larger count has a sound meaning.
    api_gap_count = distance.get('gap_count') if distance and distance.get('window_matches') else None
    page_gap_counts = [p['gapCount'] for p in pages if type(p.get('gapCount')) is int and p['gapCount'] >= 0]
    pages_clean = bool(pages) and all(p.get('gapCount') == 0 and p.get('excludedCount') == 0 and not p.get('limitExceeded') for p in pages)
    edges = (bool(points) and (points[0]['time']-start).total_seconds() <= EDGE_SECONDS
             and (end-points[-1]['time']).total_seconds() <= EDGE_SECONDS)
    full = (history['complete'] and not quality.get('locally_excluded') and not quality.get('limit_exceeded')
            and not quality.get('trailing_untrusted') and pages_clean and edges and len(points) >= 2
            and not rejected and not measured['signal_gaps'] and distance is not None
            and distance['complete'] and distance['window_matches'] and distance['gap_count'] == 0
            and distance.get('source') == 'GPS_TRACK' and distance.get('distanceKm') is not None)
    trusted_distance = distance if distance and distance.get('source') == 'GPS_TRACK' else None
    observed = trusted_distance.get('observedDistanceKm') if trusted_distance else None
    if observed is None and trusted_distance: observed = trusted_distance.get('distanceKm')
    if distance and not trusted_distance: report['limitations'].append('DISTANCE_SOURCE_NOT_GPS')
    source = 'ATIL_DISTANCE' if observed is not None else 'GPS_POINTS' if measured['distance_km'] is not None else None
    if observed is None: observed = measured['distance_km']
    report['gps'].update(distance_km=distance['distanceKm'] if full else None, observed_distance_km=observed,
                         distance_source=source, complete=bool(full), points=measured['points'],
                         signal_gaps=measured['signal_gaps'], local_signal_gaps=measured['signal_gaps'],
                         api_signal_gaps=api_gap_count, api_history_gap_counts=page_gap_counts,
                         observed_stop_minutes=measured['observed_stop_minutes'],
                         observed_moving_minutes=measured['observed_moving_minutes'], last_signal_at=measured['last_signal_at'],
                         stops=stops[:20], stop_count=len(stops), quality={**quality, 'locally_rejected': rejected,
                            'edge_tolerance_seconds': EDGE_SECONDS, 'window_edges_observed': bool(edges)})
    report['fuelings'], fueling_limits = fueling_context(fuelings, points, start, end)
    report['limitations'].extend(fueling_limits)
    report['fueling_count'] = len(fuelings) if fuelings is not None else None
    report['fueling_returned'] = len(report['fuelings'])
    if not full: comparison['reasons'].append('GPS_WINDOW_INCOMPLETE')
    comparison['gps_distance_km'] = report['gps']['distance_km']
    if full and comparison['document_distance_km'] is not None:
        comparison['distance_comparable'] = True
        comparison['difference_km'] = rounded(number(comparison['document_distance_km'])-number(comparison['gps_distance_km']))
    if doc['issues']: comparison['reasons'].extend(doc['issues'])
    if not fuel: comparison['reasons'].append('FUEL_TYPE_UNKNOWN')
    if doc['consumed_liters'] is None: comparison['reasons'].append('FUEL_CONSUMPTION_UNKNOWN')
    if not doc['balance_testable']: report['limitations'].append('FUEL_BALANCE_INCOMPLETE')
    if comparison['gps_distance_km'] == 0: comparison['reasons'].append('ZERO_GPS_DISTANCE')
    # metrics() applies the same fuel/unit/mode gates to GPS, context, ledger
    # and peer evidence, so the model cannot see a contradictory document rate.
    rate_allowed = (full and comparison['gps_distance_km'] > 0 and comparison['consumed_liters'] is not None
                    and comparison['consumed_liters'] >= 0 and not doc['issues'] and bool(fuel)
                    and not {'ENGINE_HOUR_MODE_NO_DISTANCE_RATE','CALCULATION_MODE_UNKNOWN'}.intersection(comparison['reasons']))
    if rate_allowed:
        comparison['comparable'] = True
        comparison['liters_per100km'] = rounded(number(comparison['consumed_liters'])/number(comparison['gps_distance_km'])*100)
        policy, reasons = norm_for_window(norms, target, start, end)
        comparison['reasons'].extend(reasons)
        if policy:
            comparison['norm_per100km'] = rounded(policy['liters_per100km'])
            expected = number(comparison['gps_distance_km'])*policy['liters_per100km']/100
            comparison['expected_liters'] = rounded(expected)
            if policy['tolerance_percent'] is not None:
                comparison['tolerance_percent'] = rounded(policy['tolerance_percent'])
                allowed = expected*(1+policy['tolerance_percent']/100)
                comparison['excess_liters'] = rounded(max(Decimal(0), number(comparison['consumed_liters'])-allowed))
    report['status'] = 'COMPLETE' if full and comparison['comparable'] and not comparison['reasons'] else 'PARTIAL' if points or observed is not None else 'UNAVAILABLE'
    return finish()


def narrative(report):
    def n(value): return 'noma’lum' if value is None else str(round(float(value), 2)).removesuffix('.0')
    def at(value): return value.astimezone(clock.TIMEZONE).strftime('%d.%m.%Y %H:%M') if value else 'vaqti noma’lum'
    def card(key, title, text, details=None, severity='normal'):
        return {'id': key, 'title': title, 'text': text, 'severity': severity, 'details': details or []}
    g, c = report['gps'], report['comparison']
    if report['error']:
        reasons = {'ACTUAL_TRIP_TIME_WINDOW_UNKNOWN_OR_INVALID': 'Reysning haqiqiy chiqish yoki qaytish vaqti to‘liq va to‘g‘ri kiritilmagan.',
                   'TRIP_NOT_COMPLETED': 'Reys hali yakunlanmagan.', 'TRIP_WINDOW_IN_FUTURE': 'Reys vaqti kelajakda ko‘rsatilgan.',
                   'TRIP_WINDOW_TOO_LONG': 'Reys davri hozirgi tekshiruv chegarasidan uzun.',
                   'GPS_NOT_CONFIGURED': 'GPS xizmatiga ulanish sozlanmagan.', 'ACCESS_DENIED': 'GPS ma’lumotini o‘qish ruxsati olinmadi.'}
        return {'title': 'Reysning GPS va yoqilg‘i tahlili', 'blocks': [card('gps_unavailable', 'GPS tekshiruvi',
            reasons.get(report['error'], 'Reys uchun GPS tarixi hozir olinmadi.')+' Masofa va GPS asosidagi sarf noma’lum. Bu transport ishlamaganini bildirmaydi.', severity='caution')]}
    blocks = []
    if g['complete']:
        text = f"Reys oralig‘ida GPS masofasi {n(g['distance_km'])} km. "
        if c['distance_comparable']:
            text += f"Yo‘l varaqasida {n(c['document_distance_km'])} km; hujjat minus GPS farqi {n(c['difference_km'])} km. Farq tekshirish uchun berildi, ayblov emas."
        else: text += 'Hujjatdagi yaroqli masofa yetishmagani uchun farq hisoblanmadi.'
    else:
        text = ('GPS tarixida kuzatilgan masofa '+n(g['observed_distance_km'])+' km. ' if g['observed_distance_km'] is not None else 'GPS masofasi noma’lum. ')
        if g['distance_source'] == 'GPS_POINTS': text += 'Bu nuqtalardan hisoblangan taxminiy masofa. '
        text += 'Reys davrining to‘liq qamrovi tasdiqlanmadi; shu masofadan 100 km sarf yoki ortiqcha sarf xulosasi chiqarilmadi.'
    blocks.append(card('gps_distance', 'Hujjat va GPS masofasi', text, severity='normal' if g['complete'] else 'caution'))
    if c['comparable']:
        text = f"Shu reys hujjatida {n(c['consumed_liters'])} litr sarf qayd etilgan. GPS masofasiga nisbatan {n(c['liters_per100km'])} litr / 100 km. Bu datchik o‘lchovi emas. "
        if c['norm_per100km'] is not None:
            text += f"Davrga mos norma {n(c['norm_per100km'])} litr / 100 km. "
            text += f"Ruxsat etilgan chetlanish hisobga olingach ortiqcha {n(c['excess_liters'])} litr." if c['excess_liters'] is not None else 'Ruxsat etilgan chetlanish belgilanmagan; ortiqcha sarf bahosi chiqarilmadi.'
        else: text += 'Davrga mos yagona masofa normasi tasdiqlanmadi.'
    elif 'ENGINE_HOUR_MODE_NO_DISTANCE_RATE' in c['reasons']:
        text = 'Bu reys motor-soat yoki kilometr va motor-soat aralash rejimida hisoblanadi. Faqat yurishga tegishli sarf ajratilmagani uchun umumiy sarf kilometrlarga bo‘linmadi.'
    elif 'CALCULATION_MODE_UNKNOWN' in c['reasons']:
        text = 'Sarfni kilometr yoki motor-soat bo‘yicha hisoblash rejimi tasdiqlanmagan. Shu sabab 100 km sarf hisoblanmadi.'
    else: text = 'GPS qamrovi, hujjatdagi sarf yoki o‘lchov birligi yetarli tasdiqlanmagani uchun 100 km sarf hisoblanmadi.'
    blocks.append(card('gps_consumption', 'GPS masofasi bo‘yicha sarf', text, severity='normal' if c['comparable'] else 'caution'))
    text = f"GPS kuzatuvida to‘xtash {n(g['observed_stop_minutes'])} daqiqa, harakat {n(g['observed_moving_minutes'])} daqiqa. "
    if g.get('api_signal_gaps') is not None:
        text += f"Shu reys oralig‘i uchun GPS API bildirgan uzilishlar: {n(g['api_signal_gaps'])}. "
    elif any(g.get('api_history_gap_counts', [])):
        text += 'GPS API tarix sahifalarida uzilishlar qayd etilgan; reys bo‘yicha yagona son tasdiqlanmagan. '
    text += f"Nuqtalarni tekshirishda aniqlangan uzilgan oraliqlar: {n(g.get('local_signal_gaps', g['signal_gaps']))}. "
    text += 'API va nuqtalar bo‘yicha uzilish sonlari alohida mezonlar bilan aniqlanadi, ular qo‘shilmaydi. Harakat va to‘xtash vaqti faqat kuzatilgan oraliqlar uchun. To‘xtash dvigatel ishlaganini yoki yoqilg‘i sarflanganini isbotlamaydi.'
    details = [f"{at(s['from_at'])} — {at(s['to_at'])}: {n(s['observed_minutes'])} daqiqa to‘xtash, {s['latitude']:.5f}, {s['longitude']:.5f} koordinatada." for s in g['stops']]
    if g.get('stop_count', 0) > len(details): text += ' Tafsilotda dastlabki yigirmata to‘xtash ko‘rsatilgan.'
    blocks.append(card('gps_stops', 'Harakat va kuzatilgan to‘xtashlar', text, details))
    details = []
    for item in report['fuelings']:
        if item['status'] == 'LOCATION_OBSERVED':
            text = f"{at(item['occurred_at'])} dagi quyish qaydiga {n(item['time_difference_seconds'])} soniya yaqin GPS nuqtasi topildi: {item['latitude']:.5f}, {item['longitude']:.5f}. "
            if item['distance_to_station_meters'] is not None:
                text += f"Shu nuqtadan qayd etilgan shoxobchagacha to‘g‘ri masofa {n(item['distance_to_station_meters'])} metr. Bu quyish amalga oshganini tasdiqlamaydi."
            else: text += 'Shoxobcha koordinatasi yo‘q; joy mosligi tasdiqlanmadi.'
        else:
            text = f"{at(item['occurred_at'])} dagi quyish qaydi uchun " + ('vaqt reys oralig‘iga kirmaydi.' if item['status'] == 'OUTSIDE_TRIP_WINDOW' else 'vaqt yoki shu vaqtga yaqin GPS nuqtasi yetarli emas.')
        details.append(text)
    total = report.get('fueling_count')
    text = ('Quyish yozuvlari olinmadi.' if total is None else 'Shu yo‘l varaqasiga bog‘langan quyish yozuvi topilmadi; bu yoqilg‘i quyilmaganini isbotlamaydi.' if total == 0
            else f'{len(details)} ta quyish qaydining vaqti GPS tarixi bilan solishtirildi. GPS nuqtasi quyishning mustaqil tasdig‘i emas.')
    if total is not None and total > len(details): text += ' Yozuvlar soni chegaralangan; qolgan quyishlar tekshirilmadi va jami son tasdiqlanmagan.'
    blocks.append(card('gps_fuelings', 'Quyish vaqti va joylashuv', text, details))
    return {'title': 'Reysning GPS va yoqilg‘i tahlili', 'blocks': blocks}
