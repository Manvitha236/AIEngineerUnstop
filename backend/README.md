# AI Support Email Assistant Backend

Initial scaffold with FastAPI.

Run (after creating virtual env and installing requirements):

## Install (Layered Dependencies)

Fast (core only):
```
pip install -r requirements-base.txt
```

Add ML / RAG stack when needed:
```
pip install -r requirements-ml.txt
```

Or everything in one go (slower):
```
pip install -r requirements.txt
```

## Run Dev Server

From project root use module path including backend package:
```
uvicorn backend.app.main:app --reload
```

Or change into backend first:
```
cd backend
uvicorn app.main:app --reload
```

Or use the helper script (stays in root, sets proper import path):
```
python run_server.py
```

## New Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/emails/ | List emails (urgent first) |
| POST | /api/emails/ingest | Ingest a new email payload |
| POST | /api/emails/{id}/resolve | Mark email resolved |
| POST | /api/emails/{id}/regenerate | Regenerate AI response immediately |
| PUT | /api/emails/{id}/response | Manually update/save final response |
| POST | /api/emails/fetch/start | Start background IMAP polling |
| POST | /api/emails/fetch/stop | Stop background IMAP polling |
| GET | /api/analytics/summary | Aggregated counts & metrics |

Background polling uses env vars: EMAIL_IMAP_HOST, EMAIL_IMAP_USER, EMAIL_IMAP_PASSWORD, EMAIL_POLL_INTERVAL.

Queue worker automatically processes new ingested emails to create AI responses when ML deps (OpenAI) are available; otherwise fallback text is stored.

## Tests
Run basic tests:
```
pytest -q
```
