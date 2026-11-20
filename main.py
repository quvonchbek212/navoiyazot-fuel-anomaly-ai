"""Navoiyazot Logistics: Fuel & Oil Consumption Detection Service."""
import logging
import uvicorn
from fastapi import FastAPI
from oil_detection.router import router as oil_router
from oil_detection.web import router as oil_web_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Navoiyazot Logistics · Fuel & Oil Detection API",
    description="Fuel consumption anomaly detection, theft identification, and GPS fuel cross-auditing for Navoiyazot plant.",
    version="1.0.0"
)

app.include_router(oil_router)
app.include_router(oil_web_router)

@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "oil-detection"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
