# Navoiyazot Logistics · Fuel & Oil Anomaly Detector

Enterprise audit and anomaly detection engine for monitoring diesel fuel, motor oil, and hydraulic fluid usage across the **Navoiyazot industrial heavy transport fleet**.

---

## Key Capabilities

* **Consumption Over-Limit Audit**: Detects vehicles exceeding factory-established fuel norms and seasonal quotas.
* **GPS Telemetry Cross-Auditing**: Compares actual GPS distance travelled against reported waybill mileage to prevent fraudulent log entries.
* **Theft & Fuel Drain Detection**: Flags suspicious night-time tank level drops, unauthorized idling, and off-route fuel deviations.
* **Audit Dossier Generation**: Generates structured forensic evidence cards with exact deviations and timestamps.

---

## Tech Stack

* **Language**: Python 3.12+
* **Framework**: FastAPI / Pydantic v2
* **Analytics**: Statistical outlier detection, cohort deviation scoring
* **Database Driver**: Psycopg2-binary (PostgreSQL)
* **Data Sources**: Waybill logs, GPS tracker streams, fuel dispensary logs

---

## Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/oil-detection/scan` | Scan fleet for fuel and fluid overconsumption anomalies |
| `GET` | `/oil-detection/gps-daily` | Compare daily GPS distance against recorded fuel usage |
| `GET` | `/oil-detection/evidence` | Structured audit evidence and deviation dossier for vehicle |
| `GET` | `/healthz` | Service health status |

---

## Quick Start

### 1. Installation
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration
```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=atil_navoiyazot
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. Run Service
```bash
python main.py
# Server runs on http://localhost:8002 (Docs: http://localhost:8002/docs)
```
