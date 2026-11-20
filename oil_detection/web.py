"""Browser workspace and authenticated, bounded document lookup."""
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from oil_detection import detector, rules
from oil_detection.investigation_queries import select
from oil_detection.queries import OilDataError
from security import require_api_credentials

ROOT = Path(__file__).resolve().parent
router = APIRouter(prefix='/oil-detection', tags=['Yoqilg‘i ish oynasi'])
api = APIRouter(dependencies=[Depends(require_api_credentials)])


@router.get('', include_in_schema=False)
@router.get('/', include_in_schema=False)
def workspace():
    return FileResponse(ROOT/'frontend/index.html', headers={'Cache-Control': 'no-store'})


@router.get('/assets/{name}', include_in_schema=False)
def asset(name: str):
    if name not in ('app.js', 'style.css'):
        raise HTTPException(404)
    return FileResponse(ROOT/'frontend'/name, headers={'Cache-Control': 'no-store'})


@api.get('/session')
def session(user=Depends(require_api_credentials)):
    return {'user': user}


@api.get('/waybills')
def waybills(date_from: date, date_to: date, search: str = Query('', max_length=100)):
    if date_from > date_to:
        raise HTTPException(400, 'Boshlanish sanasi tugash sanasidan katta bo‘lmasin.')
    try:
        rows = select("""
            select w.id::text, w.waybill_number, w.issue_date, w.status,
                   v.plate_number, v.brand, v.model, count(*) over() as total
            from waybill w
            left join transport_vehicle v on v.id=w.vehicle_id
            where w.issue_date between %s and %s
              and w.status in ('CLOSED','RETURNED')
              and (%s='' or w.waybill_number ilike %s or v.plate_number ilike %s)
            order by w.issue_date desc, w.id desc limit 100
        """, (date_from, date_to, search, '%'+search+'%', '%'+search+'%'))
    except OilDataError:
        raise HTTPException(503, 'Yo‘l varaqalarini hozir yuklab bo‘lmadi. Qayta urinib ko‘ring.')
    total = int(rows[0]['total']) if rows else 0
    return {'items': [{k: v for k, v in row.items() if k != 'total'} for row in rows],
            'total': total, 'returned': len(rows), 'truncated': total > len(rows),
            'period': {'date_from': date_from, 'date_to': date_to}}


@api.get('/flagged-vehicles')
async def flagged_vehicles(date_from: date, date_to: date):
    """Return overconsuming and suspicious vehicles for quick investigation lookup."""
    if date_from > date_to:
        raise HTTPException(400, 'Boshlanish sanasi tugash sanasidan katta bo‘lmasin.')
    try:
        report = await run_in_threadpool(
            detector.report, date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        )
    except OilDataError:
        raise HTTPException(503, 'Ortiqcha sarflagan mashinalar ro‘yxatini hozir olib bo‘lmadi.')
    top_waybill: dict[str, dict[str, str | None]] = {}
    for item in report.get('anomalies') or []:
        if item.get('source') != 'waybill':
            continue
        vid = (item.get('vehicle') or {}).get('id')
        raw_id = item.get('id') or ''
        if vid and vid not in top_waybill and raw_id.startswith('waybill:'):
            top_waybill[vid] = {'waybill_id': raw_id[8:], 'document_number': item.get('document_number')}
    items = []
    for row in report.get('vehicles') or []:
        if not row.get('finding_records'):
            continue
        vehicle = row.get('vehicle') or {}
        vid = vehicle.get('id')
        wb = top_waybill.get(vid, {}) if vid else {}
        flag_codes = [
            code for code in (row.get('flags') or {})
            if rules.FLAG_KIND.get(code, rules.KIND_DATA_GAP) != rules.KIND_DATA_GAP
        ] or list((row.get('flags') or {}).keys())
        items.append({
            'vehicle_id': vid,
            'plate_number': vehicle.get('plate_number'),
            'brand': vehicle.get('brand'),
            'model': vehicle.get('model'),
            'finding_records': row.get('finding_records', 0),
            'overconsuming': bool(row.get('over_limit_liters', 0) > 0 or 'CONSUMPTION_OVER_NORM' in (row.get('flags') or {})),
            'excess_liters': row.get('excess_liters', 0.0),
            'unaccounted_liters': row.get('unaccounted_liters', 0.0),
            'over_limit_liters': row.get('over_limit_liters', 0.0),
            'flag_titles': [rules.flag_title(code, 'uz') for code in flag_codes][:4],
            'waybill_id': wb.get('waybill_id'),
            'document_number': wb.get('document_number') or ((row.get('documents') or [None])[0]),
        })
    summary = report.get('summary') or {}
    return {
        'items': items,
        'overconsuming_vehicles': summary.get('overconsuming_vehicles', 0),
        'vehicles_with_finding': summary.get('vehicles_with_finding', len(items)),
        'period': {'date_from': date_from, 'date_to': date_to},
    }


router.include_router(api)
