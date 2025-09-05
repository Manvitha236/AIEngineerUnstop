from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Optional, Any, Dict
from sqlalchemy.orm import Session
from ..schemas.email import EmailOut, EmailCreate, ExtractedInfo
from ..services.email_service import (
    create_email,
    list_emails as list_db_emails,
    mark_resolved,
    get_email,
    save_auto_response,
    approve_email,
    mark_sent,
)
from ..services.background_fetcher import start_background_fetch, stop_background_fetch, get_last_fetch_summary
from ..services.retrievers import set_runtime_provider, get_runtime_provider
from ..services.retrievers import fetch_any, gmail_diag
from ..db.database import get_db
from ..services.nlp import analyze_sentiment, determine_priority, extract_info
from ..services.auto_responder import generate_response
from ..services.auto_responder import ai_diagnostics, test_gemini
from ..services.dataset_loader import load_dataset
from ..security.api_key import get_api_key
from ..core.events import broadcaster
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

def _coerce_received(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            dt = parsedate_to_datetime(value)
            if dt:
                return dt
        except Exception:
            pass
    return datetime.now(timezone.utc)
import os, threading, logging

# Optional RAG engine (heavy deps). Only active if ML requirements installed.
try:  # pragma: no cover - import guard
    from ..core.rag import RagEngine  # type: ignore
except Exception:  # sentence_transformers/faiss not installed yet
    RagEngine = None  # type: ignore

router = APIRouter()

rag_engine = None  # will hold RagEngine instance if available

# Track RAG lifecycle state for health/status endpoints
rag_state = {
    "mode": "off",      # off | lazy | sync
    "status": "disabled"  # disabled | loading | ready | error
}

# Startup is now handled via app lifespan in main.py; router exposes an init function.
def init_rag_engine():  # pragma: no cover
    """Build the RAG engine (blocking). Caller is responsible for setting rag_state beforehand."""
    global rag_engine, rag_state
    if RagEngine is None:
        rag_state["status"] = "disabled"
        return
    try:
        instance = RagEngine()
        instance.build([
            "If a user cannot access their account, advise password reset or SSO health check.",
            "Critical outages should be escalated to the on-call engineer within 15 minutes.",
            "For billing queries, direct the customer to the billing portal and create a ticket if unresolved."
        ])
        rag_engine = instance
        rag_state["status"] = "ready"
        logging.getLogger(__name__).info("RAG engine ready", extra={"component":"rag","status":"ready"})
    except Exception as e:
        rag_engine = None
        rag_state["status"] = "error"
        logging.getLogger(__name__).warning("RAG engine failed to initialize", exc_info=e)


def schedule_rag_engine(mode: str):  # pragma: no cover
    """Schedule RAG engine according to mode: off|lazy|sync.
    - off: do nothing
    - lazy: start in background thread
    - sync: build immediately (blocking)
    """
    mode = (mode or '').lower()
    if mode not in {"off", "lazy", "sync"}:
        mode = "lazy"  # default
    rag_state["mode"] = mode
    if RagEngine is None:
        rag_state["status"] = "disabled"
        return
    if mode == "off":
        rag_state["status"] = "disabled"
        return
    rag_state["status"] = "loading"
    if mode == "sync":
        init_rag_engine()
    else:  # lazy
        def _runner():
            try:
                init_rag_engine()
            except Exception:
                pass
        threading.Thread(target=_runner, name="rag-init", daemon=True).start()

@router.post("/maintenance/recompute", dependencies=[Depends(get_api_key)])
def maintenance_recompute(limit_details: int = 50, include_details: bool = True, db: Session = Depends(get_db)):
    """Re-run sentiment/priority and provide fresh extraction preview for all emails.

    Returns up to `limit_details` detailed extraction objects (not persisted) so the frontend can refresh caches.
    """
    from ..models.email_model import Email
    emails = db.query(Email).all()
    changed = 0
    details = []
    for i, e in enumerate(emails):
        new_sent = analyze_sentiment(e.body)
        new_pri = determine_priority(e.body)
        if new_sent != e.sentiment or new_pri != e.priority:
            e.sentiment = new_sent
            e.priority = new_pri
            changed += 1
        if include_details and i < limit_details:
            phones, alt_emails, keywords, requested_actions, sentiment_terms = extract_info(e.body)
            details.append({
                "id": e.id,
                "sentiment": e.sentiment,
                "priority": e.priority,
                "extracted": {
                    "phone_numbers": phones,
                    "alt_emails": alt_emails,
                    "keywords": keywords,
                    "requested_actions": requested_actions,
                    "sentiment_terms": sentiment_terms
                }
            })
    if changed:
        db.commit()
    return {"total": len(emails), "changed_sentiment_or_priority": changed, "details_returned": len(details), "details": details}


@router.post("/maintenance/reset-dataset", dependencies=[Depends(get_api_key)])
def maintenance_reset_dataset(
    generate_responses: bool = False,
    dataset_path: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Wipe existing emails and load from the provided CSV dataset.

    Parameters:
        generate_responses: if True, queue auto-response generation for each loaded email.
        dataset_path: optional override path to CSV (defaults to env DATASET_CSV_PATH or bundled sample name).
    """
    import os
    path = dataset_path or os.getenv("DATASET_CSV_PATH", "68b1acd44f393_Sample_Support_Emails_Dataset.csv")
    try:
        summary = load_dataset(db, path, generate_responses=generate_responses, wipe=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Dataset file not found: {path}")
    return summary


def rag_status():  # pragma: no cover
    return {"mode": rag_state["mode"], "status": rag_state["status"], "available": rag_engine is not None and rag_state["status"] == "ready"}

@router.get("/")
def list_emails(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Free text search across sender, subject, body"),
    search: Optional[str] = Query(None, description="Alias for q"),
    query: Optional[str] = Query(None, description="Alias for q"),
    domain: Optional[str] = Query(None, description="Filter by sender domain (example.com, @example.com, or fragment)"),
    fuzzy: bool = Query(False, description="Apply lightweight token-all-must-match fuzzy on subject+body (post-filter)."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None, description="Filter by source (demo/gmail/imap)"),
    only_live: bool = Query(False, description="Shortcut: show only gmail live emails (overrides source & exclude)")
):
    # Accept multiple aliases for search
    if not q:
        q = search or query
    # normalize priority filter to canonical values
    if priority:
        if priority.lower() == 'urgent':
            priority = 'Urgent'
        elif priority.lower() in ['not urgent','normal','low','high']:
            # for now only two buckets; treat any non urgent as 'Not urgent'
            priority = 'Not urgent'
    # normalize sentiment to stored canonical capitalization
    if sentiment:
        sl = sentiment.lower()
        if sl.startswith('pos'):
            sentiment = 'Positive'
        elif sl.startswith('neg'):
            sentiment = 'Negative'
        elif sl.startswith('neu'):
            sentiment = 'Neutral'
    # Decide source filtering strategy
    runtime_provider = get_runtime_provider()
    exclude_sources = None
    source_filter = source
    if only_live:
        source_filter = 'gmail'
        exclude_sources = None
    elif source_filter:
        # user explicitly requested a source; do not auto-exclude anything
        pass
    else:
        # In live gmail mode hide demo by default
        if runtime_provider == 'gmail':
            exclude_sources = ['demo']

    records, total = list_db_emails(
        db,
        status=status,
        priority=priority,
        sentiment=sentiment,
        q_search=q,
        domain=domain,
        fuzzy=fuzzy,
        limit=limit,
        offset=offset,
        source=source_filter,
        exclude_sources=exclude_sources
    )
    # If fuzzy applied, adjust total to visible count
    if fuzzy and q:
        total = len(records)
    items: List[Dict[str, Any]] = []
    for r in records:
        items.append(EmailOut(
            id=r.id,
            sender=r.sender,
            subject=r.subject,
            body=r.body,
            received_at=r.received_at,
            source=getattr(r, 'source', None),
            external_id=getattr(r, 'external_id', None),
            sentiment=r.sentiment,
            priority=r.priority,
            auto_response=r.auto_response,
            status=r.status,
            extracted=ExtractedInfo(sentiment=r.sentiment, priority=r.priority)
        ).model_dump())
    return {"total": total, "count": len(items), "items": items, "limit": limit, "offset": offset}

@router.post("/kb/docs", dependencies=[Depends(get_api_key)])
def add_kb_doc(text: str = Body(..., embed=True)):
    if rag_engine is None:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    rag_engine.add_doc(text)
    return {"status": "added", "size": len(rag_engine.store.meta)}

@router.get("/kb/docs")
def list_kb_docs():
    if rag_engine is None:
        return {"docs": []}
    return {"docs": rag_engine.store.meta, "size": len(rag_engine.store.meta)}

@router.post("/ingest", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def ingest_email(payload: EmailCreate, db: Session = Depends(get_db)):
    sentiment = analyze_sentiment(payload.body)
    priority = determine_priority(payload.body)
    phones, alt_emails, keywords, requested_actions, sentiment_terms = extract_info(payload.body)
    # Queue-based deferred auto-response
    record = create_email(db, payload, sentiment, priority, auto_response=None)
    from ..services.queue_worker import enqueue_email  # local import to avoid cycle
    enqueue_email(record.id, priority)
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(
            phone_numbers=phones,
            alt_emails=alt_emails,
            sentiment=sentiment,
            priority=priority,
            keywords=keywords,
            requested_actions=requested_actions,
            sentiment_terms=sentiment_terms
        )
    )

@router.get("/{email_id}", response_model=EmailOut)
def get_single_email(email_id: int, db: Session = Depends(get_db)):
    record = get_email(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    phones, alt_emails, keywords, requested_actions, sentiment_terms = extract_info(record.body)
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(
            phone_numbers=phones,
            alt_emails=alt_emails,
            sentiment=record.sentiment,
            priority=record.priority,
            keywords=keywords,
            requested_actions=requested_actions,
            sentiment_terms=sentiment_terms
        )
    )

@router.post("/{email_id}/regenerate", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def regenerate_response(email_id: int, db: Session = Depends(get_db)):
    record = get_email(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    rag_results = []
    if rag_engine:
        rag_results = rag_engine.retrieve(record.subject + "\n" + record.body)
    auto_resp = generate_response(record.subject, record.body, record.sentiment, record.priority, rag_results)
    save_auto_response(db, record, auto_resp)
    phones, alt_emails, keywords, requested_actions, sentiment_terms = extract_info(record.body)
    try:
        broadcaster.publish("email_updated", f"{{\"id\":{record.id},\"status\":\"{record.status}\"}}")
    except Exception:
        pass
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(
            phone_numbers=phones,
            alt_emails=alt_emails,
            sentiment=record.sentiment,
            priority=record.priority,
            keywords=keywords,
            requested_actions=requested_actions,
            sentiment_terms=sentiment_terms
        )
    )

@router.put("/{email_id}/response", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def update_response(email_id: int, new_text: str, db: Session = Depends(get_db)):
    record = get_email(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    save_auto_response(db, record, new_text, mark_responded=True)
    phones, alt_emails, keywords, requested_actions, sentiment_terms = extract_info(record.body)
    try:
        broadcaster.publish("email_updated", f"{{\"id\":{record.id},\"status\":\"{record.status}\"}}")
    except Exception:
        pass
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(
            phone_numbers=phones,
            alt_emails=alt_emails,
            sentiment=record.sentiment,
            priority=record.priority,
            keywords=keywords,
            requested_actions=requested_actions,
            sentiment_terms=sentiment_terms
        )
    )

@router.post("/fetch/start", dependencies=[Depends(get_api_key)])
def start_fetch():
    start_background_fetch()
    return {"status": "started"}

@router.post("/fetch/stop", dependencies=[Depends(get_api_key)])
def stop_fetch():
    stop_background_fetch()
    return {"status": "stopped"}

def _do_single_fetch(db: Session):
    try:
        mails = fetch_any(limit=10)
        created = 0
        if mails:
            from ..services.email_service import create_email, email_exists
            from ..schemas.email import EmailCreate
            for m in mails:
                sentiment = analyze_sentiment(m['body'])
                priority = determine_priority(m['body'])
                auto_resp = generate_response(m['subject'], m['body'], sentiment, priority, [])
                recv = _coerce_received(m.get('received_at'))
                from ..services.email_service import email_exists_external, email_exists
                ext_id = m.get('external_id')
                if ext_id and email_exists_external(db, ext_id):
                    continue
                if not ext_id and email_exists(db, m['sender'], m['subject'], recv):
                    continue
                create_email(db, EmailCreate(sender=m['sender'], subject=m['subject'], body=m['body'], received_at=recv), sentiment, priority, auto_resp, source=get_runtime_provider(), external_id=ext_id)
                created += 1
        return {"fetched": len(mails), "inserted": created}
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc().splitlines()[-3:]}

@router.post("/fetch/run-once", dependencies=[Depends(get_api_key)])
def run_single_fetch(db: Session = Depends(get_db)):
    """Trigger a single immediate retrieval cycle (POST)."""
    return _do_single_fetch(db)

@router.get("/fetch/run-once", dependencies=[Depends(get_api_key)])
def run_single_fetch_get(db: Session = Depends(get_db)):
    """Convenience GET variant for manual browser testing."""
    return _do_single_fetch(db)

@router.get("/fetch/status", dependencies=[Depends(get_api_key)])
def fetch_status():
    """Return last background fetch summary and current provider."""
    return {"provider": get_runtime_provider(), "last": get_last_fetch_summary()}

@router.get("/fetch/diag", dependencies=[Depends(get_api_key)])
def fetch_diag():
    """Detailed Gmail diagnostic info (does not expose secrets)."""
    if get_runtime_provider() != 'gmail':
        return {"provider": get_runtime_provider(), "note": "switch to gmail for gmail diagnostics"}
    return {
        "provider": "gmail",
        "login_ok": gmail_diag.last_login_ok,
        "last_error": gmail_diag.last_error,
        "last_fetch_count": gmail_diag.last_fetch_count,
        "last_label": gmail_diag.last_label,
        "last_ts": gmail_diag.last_ts,
        "has_user": bool(os.getenv('GMAIL_USER')),
        "has_app_password": bool(os.getenv('GMAIL_APP_PASSWORD')),
    }

@router.get("/source", dependencies=[Depends(get_api_key)])
def source_info(db: Session = Depends(get_db)):
    from ..models.email_model import Email
    total = db.query(Email).count()
    return {"provider": get_runtime_provider(), "total": total}

@router.post("/purge/demo", dependencies=[Depends(get_api_key)])
def purge_demo(db: Session = Depends(get_db)):
    from ..models.email_model import Email
    removed = db.query(Email).filter(Email.source=='demo').delete()
    db.commit()
    return {"removed": removed}

@router.post("/purge/non-gmail", dependencies=[Depends(get_api_key)])
def purge_non_gmail(db: Session = Depends(get_db)):
    """Remove all emails whose source is NOT 'gmail'."""
    from ..models.email_model import Email
    removed = db.query(Email).filter(Email.source != 'gmail').delete()
    db.commit()
    return {"removed": removed}

@router.get("/ai/diag", dependencies=[Depends(get_api_key)])
def ai_diag():
    return ai_diagnostics()

@router.get("/ai/test", dependencies=[Depends(get_api_key)])
def ai_test():
    return test_gemini()

@router.post("/maintenance/tag-unknown-as-demo", dependencies=[Depends(get_api_key)])
def tag_unknown_as_demo(db: Session = Depends(get_db)):
    from ..models.email_model import Email
    updated = db.query(Email).filter(Email.source=='unknown').update({"source": "demo"})
    db.commit()
    return {"updated": updated}

# Unprotected convenience endpoint if local auth disabled
@router.get("/fetch/run-once-open")
def run_once_open(db: Session = Depends(get_db)):
    return _do_single_fetch(db)

@router.get("/fetch/ping-gmail", dependencies=[Depends(get_api_key)])
def ping_gmail():
    """Quick network reachability check to imap.gmail.com:993."""
    import socket, time
    host, port = 'imap.gmail.com', 993
    start = time.perf_counter()
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        dur = round((time.perf_counter()-start)*1000,1)
        return {"reachable": True, "ms": dur}
    except Exception as e:
        return {"reachable": False, "error": type(e).__name__+":"+str(e)}

@router.get("/auth/debug")
def auth_debug(expected: bool = True):
    """Open endpoint to show whether SUPPORT_API_KEY is set and what header name to use."""
    import os
    exp = os.getenv('SUPPORT_API_KEY')
    return {"api_key_required": bool(exp), "header_name": "X-API-Key", "have_env_value": bool(exp)}

@router.get("/fetch/mode", dependencies=[Depends(get_api_key)])
def get_fetch_mode():
    return {"provider": get_runtime_provider()}

@router.post("/fetch/mode", dependencies=[Depends(get_api_key)])
def set_fetch_mode(provider: str, reload_demo: bool = False, purge_demo: bool = True, db: Session = Depends(get_db)):
    provider = provider.lower()
    if provider == 'demo':
        # Switch to demo: stop fetcher, set runtime provider to demo (no external fetch)
        stop_background_fetch()
        set_runtime_provider('demo')
        summary = None
        if reload_demo:
            # reload dataset to ensure baseline
            try:
                from .emails import maintenance_reset_dataset  # type: ignore
            except Exception:
                summary = {"reloaded": False}
            else:
                # call helper directly
                from ..services.dataset_loader import load_dataset
                path = os.getenv("DATASET_CSV_PATH", "68b1acd44f393_Sample_Support_Emails_Dataset.csv")
                try:
                    summary = load_dataset(db, path, generate_responses=False, wipe=True)
                except FileNotFoundError:
                    summary = {"error": "dataset file not found", "path": path}
        return {"mode": "demo", "reloaded": bool(summary), "summary": summary}
    elif provider == 'gmail':
        set_runtime_provider('gmail')
        # optional purge/tag first so new live inserts are clean
        purged = 0
        tagged = 0
        if purge_demo:
            from ..models.email_model import Email
            tagged = db.query(Email).filter(Email.source=='unknown').update({"source":"demo"})
            purged = db.query(Email).filter(Email.source=='demo').delete()
            db.commit()
        # Immediate single fetch so user sees live emails without waiting for poll interval
        created = 0
        try:
            from ..services.retrievers import fetch_any
            from ..services.email_service import create_email, email_exists, email_exists_external
            from ..schemas.email import EmailCreate
            from ..services.nlp import analyze_sentiment, determine_priority
            from ..services.auto_responder import generate_response
            mails = fetch_any(limit=15)
            for m in mails:
                recv = _coerce_received(m.get('received_at'))
                ext_id = m.get('external_id')
                if ext_id and email_exists_external(db, ext_id):
                    continue
                if not ext_id and email_exists(db, m['sender'], m['subject'], recv):
                    continue
                sentiment = analyze_sentiment(m['body'])
                priority = determine_priority(m['body'])
                auto_resp = generate_response(m['subject'], m['body'], sentiment, priority, [])
                create_email(db, EmailCreate(sender=m['sender'], subject=m['subject'], body=m['body'], received_at=recv), sentiment, priority, auto_resp, source='gmail', external_id=ext_id)
                created += 1
        except Exception:
            created = -1
        start_background_fetch()
        return {"mode": "gmail", "started": True, "purged_demo": purged, "tagged_unknown_as_demo": tagged, "initial_live_fetched": created}
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider (use demo or gmail)")

@router.post("/{email_id}/resolve", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def resolve_email(email_id: int, db: Session = Depends(get_db)):
    record = mark_resolved(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(sentiment=record.sentiment, priority=record.priority)
    )

@router.post("/{email_id}/approve", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def approve(email_id: int, db: Session = Depends(get_db)):
    record = approve_email(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    try:
        broadcaster.publish("email_updated", f"{{\"id\":{record.id},\"status\":\"{record.status}\"}}")
    except Exception:
        pass
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(sentiment=record.sentiment, priority=record.priority)
    )

@router.post("/{email_id}/send", response_model=EmailOut, dependencies=[Depends(get_api_key)])
def send(email_id: int, db: Session = Depends(get_db)):
    # Simulate send (would integrate SMTP / provider)
    record = mark_sent(db, email_id)
    if not record:
        raise HTTPException(status_code=404, detail="Email not found")
    try:
        broadcaster.publish("email_updated", f"{{\"id\":{record.id},\"status\":\"{record.status}\"}}")
    except Exception:
        pass
    return EmailOut(
        id=record.id,
        sender=record.sender,
        subject=record.subject,
        body=record.body,
        received_at=record.received_at,
        sentiment=record.sentiment,
        priority=record.priority,
        auto_response=record.auto_response,
        status=record.status,
        extracted=ExtractedInfo(sentiment=record.sentiment, priority=record.priority)
    )
