from fastapi import FastAPI
from dotenv import load_dotenv
load_dotenv(dotenv_path="backend/.env", override=False)
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from .routers import emails, analytics
from .services.retrievers import get_runtime_provider
from .services.background_fetcher import start_background_fetch
from sqlalchemy import func
from .db.database import SessionLocal
from .models.email_model import Email as EmailModel
from .services.queue_worker import start_queue_worker
from .routers.emails import schedule_rag_engine, rag_status
from .db.database import Base, engine
from .models import email_model  # noqa: F401
from .core.logging import init_logging
import logging, time, uuid
from fastapi import Request
from fastapi.responses import StreamingResponse
from .core.events import broadcaster
from fastapi.responses import JSONResponse
from asyncio import create_task, sleep

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_logging()
    Base.metadata.create_all(bind=engine)
    # lightweight migration for source/external_id columns (SQLite)
    try:
        with engine.connect() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(emails)").fetchall()
            cols = [r[1] for r in rows]
            if 'source' not in cols:
                conn.exec_driver_sql("ALTER TABLE emails ADD COLUMN source TEXT DEFAULT 'unknown'")
            if 'external_id' not in cols:
                conn.exec_driver_sql("ALTER TABLE emails ADD COLUMN external_id TEXT")
    except Exception as e:
        logging.getLogger(__name__).warning("source_column_migration_failed", exc_info=e)
    start_queue_worker()
    # Determine RAG mode from env (RAG_MODE=off|lazy|sync). Default lazy to avoid startup blocking.
    import os, logging
    rag_mode = os.getenv('RAG_MODE', 'lazy')
    schedule_rag_engine(rag_mode)
    # If provider is gmail at startup, automatically start background fetcher (previously only started via mode endpoint)
    try:
        if get_runtime_provider() == 'gmail':
            start_background_fetch()
    except Exception:
        logging.getLogger(__name__).warning("failed_starting_fetcher_startup")
    # Start keepalive task
    async def _keepalive():
        while True:
            try:
                broadcaster.publish("keepalive", "{}")
            except Exception:
                pass
            await sleep(15)
    ka_task = create_task(_keepalive())
    yield
    ka_task.cancel()
    # Shutdown (add cleanup if needed)

app = FastAPI(title="AI Support Email Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(emails.router, prefix="/api/emails", tags=["emails"]) 
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"]) 


@app.get("/health")
async def health():
    # Lightweight counts for debugging provider status
    db = SessionLocal()
    total = db.query(func.count(EmailModel.id)).scalar() or 0
    db.close()
    return {"status": "ok", "rag": rag_status(), "provider": get_runtime_provider(), "emails": total}

@app.middleware("http")
async def timing_logger(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4())[:8])
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration = (time.perf_counter()-start)*1000
        logging.getLogger().info(
            f"{request.method} {request.url.path} {response.status_code} {duration:.1f}ms",
            extra={"trace_id": trace_id, "method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round(duration,1)}
        )
        response.headers['X-Trace-Id'] = trace_id
        return response
    except Exception as exc:  # pragma: no cover
        duration = (time.perf_counter()-start)*1000
        logging.getLogger().error(
            f"ERR {request.method} {request.url.path} {type(exc).__name__}",
            extra={"trace_id": trace_id, "method": request.method, "path": request.url.path, "status": 500, "duration_ms": round(duration,1)}
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error", "trace_id": trace_id})

@app.get('/_boom')  # simple test route for error logging
async def boom():  # pragma: no cover
    raise RuntimeError("Boom")

@app.get('/api/events')
async def sse_events(request: Request):  # pragma: no cover (difficult in unit tests)
    async def event_stream():
        async for msg in broadcaster.subscribe():
            # client disconnect handling
            if await request.is_disconnected():
                break
            yield msg
    return StreamingResponse(event_stream(), media_type='text/event-stream')
