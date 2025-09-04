import threading
import time
from .priority_queue import EmailPriorityQueue
from sqlalchemy.orm import Session
from ..db.database import SessionLocal
from .email_service import get_email, save_auto_response
from .nlp import analyze_sentiment, determine_priority, extract_info
from .auto_responder import generate_response
from ..core.events import broadcaster

_queue = EmailPriorityQueue()
_running = False
_thread: threading.Thread | None = None

SLEEP_INTERVAL = 2  # seconds idle wait


def enqueue_email(email_id: int, priority: str):
    _queue.push(email_id, priority)


def _worker_loop():
    global _running
    while _running:
        item = _queue.pop()
        if not item:
            time.sleep(SLEEP_INTERVAL)
            continue
        db: Session = SessionLocal()
        try:
            email = get_email(db, item.email_id)
            if not email:
                continue
            # if already has auto_response skip
            if email.auto_response:
                continue
            rag_results = []  # could integrate RAG engine via singleton import
            auto_resp = generate_response(email.subject, email.body, email.sentiment, email.priority, rag_results)
            save_auto_response(db, email, auto_resp)
            try:
                # broadcast update (minimal JSON)
                broadcaster.publish("email_updated", f"{{\"id\":{email.id},\"status\":\"responded\"}}")
            except Exception:
                pass
        finally:
            db.close()


def start_queue_worker():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_worker_loop, daemon=True)
    _thread.start()


def stop_queue_worker():
    global _running
    _running = False
