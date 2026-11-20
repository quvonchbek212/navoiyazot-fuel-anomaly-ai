"""Local fuel workspace: python -m oil_detection --port 8031."""
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from oil_detection.router import router as api_router
from oil_detection.web import router as web_router
from security import require_api_credentials


async def same_origin(request: Request):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Boshqa saytdan so‘rov rad etildi.')


app = FastAPI(title='ATIL Yoqilg‘i AI tahlili', version='1.0.0')
app.include_router(api_router, dependencies=[Depends(require_api_credentials), Depends(same_origin)])
app.include_router(web_router)


@app.get('/', include_in_schema=False)
def root():
    return RedirectResponse('/oil-detection/')


@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    if request.url.path.startswith('/oil-detection'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response
