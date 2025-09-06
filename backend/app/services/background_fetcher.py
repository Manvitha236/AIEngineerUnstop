import threading
import time
import os
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .retrievers import fetch_any, get_runtime_provider
from .nlp import analyze_sentiment, determine_priority, extract_info
from .auto_responder import generate_response
from .queue_worker import enqueue_email
from ..db.database import SessionLocal
from .email_service import create_email
from .email_service import email_exists, email_exists_external
from ..schemas.email import EmailCreate
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

_running = False
_thread = None
last_fetch_summary = {"ts": None, "fetched": 0, "provider": None}

POLL_INTERVAL = int(os.getenv('EMAIL_POLL_INTERVAL', '120'))  # seconds

def _loop():
    global _running
    log = logging.getLogger(__name__)
    while _running:
        try:
            provider = get_runtime_provider()
            mails = fetch_any(limit=20)
            if mails:
                db: Session = SessionLocal()
                for m in mails:
                    sentiment = analyze_sentiment(m['body'])
                    priority = determine_priority(m['body'])
                    # Do not call the LLM inline here to avoid bursts. Let the queue worker serialize calls.
                    auto_resp = None
                    recv = _coerce_received(m.get('received_at'))
                    ext_id = m.get('external_id')
                    if ext_id and email_exists_external(db, ext_id):
                        continue
                    if not ext_id and email_exists(db, m['sender'], m['subject'], recv):
                        continue
                    email = create_email(db, EmailCreate(
                        sender=m['sender'],
                        subject=m['subject'],
                        body=m['body'],
                        received_at=recv
                        ), sentiment, priority, auto_resp, source=provider, external_id=ext_id)
                    try:
                        enqueue_email(email.id, priority)
                    except Exception:
                        pass
                db.close()
                log.info("fetch_cycle", extra={"provider":provider, "fetched":len(mails)})
                last_fetch_summary.update({
                    "ts": datetime.utcnow().isoformat()+"Z",
                    "fetched": len(mails),
                    "provider": provider
                })
            else:
                log.debug("fetch_cycle_empty", extra={"provider":provider})
                last_fetch_summary.update({
                    "ts": datetime.utcnow().isoformat()+"Z",
                    "fetched": 0,
                    "provider": provider
                })
        except Exception:
            log.exception("fetch_cycle_error")
        time.sleep(POLL_INTERVAL)

def start_background_fetch():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()


def stop_background_fetch():
    global _running
    _running = False

def get_last_fetch_summary():
    return last_fetch_summary
