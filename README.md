# Django Payroll Engine

> **Portfolio Project 2** — Targeting the Senior Python Django GCP Engineer role  
> Tech: Python · Django REST Framework · Celery · Redis · MySQL · Docker · ReportLab

A high-throughput asynchronous payroll processing system designed to handle complex payroll calculations, timesheet approvals, and PDF invoice generation. By offloading CPU-intensive PDF rendering to background Celery workers, it achieves low-latency API response times and ensures strict database transaction integrity (ACID) for financial compliance.

---

## 🎯 What This Project Demonstrates

| JD Requirement | Implementation |
|---|---|
| Expert Python Django | DRF ViewSets, MTV architecture, custom management commands |
| ORM optimization | `select_related`, `prefetch_related`, `bulk_create`, compound indexes |
| Threading limitations / multi-process | CPU-bound PDF generation offloaded to Celery workers |
| MySQL + financial correctness | `DECIMAL(12,2)` fields throughout — never `float` |
| ACID transactions | `@transaction.atomic` wraps every payroll run |
| Linux / Docker deployment | Multi-service Docker Compose with health checks |
| GCP-ready | Swap local file storage for GCP Cloud Storage bucket in one line |

---

## 🏗️ Architecture

```
HTTP Request
    │
    ▼
┌───────────────────────────────────────┐
│  Django REST Framework API (gunicorn)  │
│  POST /api/payroll-runs/               │──→ Returns 202 + task_id immediately
└────────────────┬──────────────────────┘
                 │ .delay()
                 ▼
┌───────────────────────────────────────┐
│  Redis (Message Broker)                │
└────────────────┬──────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────┐
│  Celery Worker (separate process)      │
│  run_payroll_task()                    │
│    → calculate_worker_pay() x N        │
│    → bulk_create(entries)              │  All in one ACID transaction
│    → generate_invoice_pdf_task.delay() │──→ Fan out per worker
└────────────────┬──────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────┐
│  MySQL Database                        │
│  DECIMAL fields, compound indexes      │
└───────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+, pip, Docker

### 1. Clone & Virtual Environment

```bash
git clone <repo-url>
cd django-payroll-engine

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env if needed
```

### 3. Start Services (MySQL + Redis)

```bash
docker compose up mysql redis -d
```

### 4. Run Migrations & Seed

```bash
python manage.py migrate
python manage.py seed_demo
```

### 5. Start Django API

```bash
python manage.py runserver
```

### 6. Start Celery Worker (new terminal)

```bash
celery -A payroll_engine worker --loglevel=info
```

---

## 🐳 Run Everything with Docker Compose

```bash
docker compose up --build
# Apply migrations inside the running container:
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed_demo
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/agencies/` | List agencies |
| POST | `/api/workers/` | Create a care worker |
| POST | `/api/shifts/` | Log a completed shift |
| GET | `/api/shifts/?worker=1` | Filter shifts by worker |
| **POST** | **`/api/payroll-runs/`** | **Trigger async payroll (returns 202)** |
| GET | `/api/payroll-runs/{id}/` | Poll status + view entries |
| POST | `/api/payroll-runs/{id}/generate-invoices/` | Fan out PDF generation |
| GET | `/api/payroll-entries/{id}/invoice/` | Download PDF invoice |
| GET | `/api/docs/` | **Swagger UI** |

### Example: Trigger a Payroll Run

```bash
curl -X POST http://localhost:8000/api/payroll-runs/ \
  -H "Content-Type: application/json" \
  -d '{"agency": 1, "period_start": "2025-05-01", "period_end": "2025-05-31"}'

# Returns instantly:
# {"id": 1, "status": "QUEUED", "celery_task_id": "abc-123", "message": "..."}

# Poll for completion:
curl http://localhost:8000/api/payroll-runs/1/
```

---

## 🧪 Running Tests

```bash
python manage.py test payroll
```

Tests cover:
- ✅ Regular pay calculation
- ✅ Overtime calculation (1.5x multiplier)
- ✅ **Decimal precision** — proves no floating-point errors
- ✅ ACID transaction rollback on failure
- ✅ API validation (end_time before start_time)
- ✅ 202 Accepted response for async payroll runs

---

## 💡 Key Technical Decisions

### Why `DECIMAL` not `float`?
```python
# Python float (WRONG for money)
>>> 0.1 + 0.2
0.30000000000000004  # ❌ Payroll error!

# Python Decimal (CORRECT)
>>> Decimal('0.1') + Decimal('0.2')
Decimal('0.3')      # ✅ Exact
```

### Why Celery for PDF generation?
PDF generation is CPU-bound. Running it synchronously would block the Django thread, preventing it from serving other requests. Celery workers run in separate processes, bypassing the Python GIL entirely.

### Why `@transaction.atomic`?
If the server crashes mid-payroll, a partial write would mean some workers are paid and others aren't — money vanishes. `@transaction.atomic` guarantees that either all entries are committed or none are.

---

## 🌐 GCP Deployment (Cloud Run)

```bash
# Build and push to GCP Artifact Registry
gcloud builds submit --tag gcr.io/PROJECT_ID/payroll-engine

# Deploy API to Cloud Run
gcloud run deploy payroll-api \
  --image gcr.io/PROJECT_ID/payroll-engine \
  --set-env-vars MYSQL_HOST=...,REDIS_URL=...

# Swap media storage → GCP Cloud Storage
# In tasks.py, replace open(filepath, 'wb') with:
# bucket.blob(f"invoices/{filename}").upload_from_file(buffer)
```
