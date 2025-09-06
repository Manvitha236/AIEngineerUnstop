import threading
import time
import logging
import os
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
MAX_ATTEMPTS_PER_EMAIL = 3
_attempt_counts: dict[int, int] = {}


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
            try:
                auto_resp = generate_response(email.subject, email.body, email.sentiment, email.priority, rag_results)
            except Exception as e:
                # On transient/provider errors (e.g., 429 cooldown), re-enqueue and continue
                attempts = _attempt_counts.get(item.email_id, 0) + 1
                _attempt_counts[item.email_id] = attempts
                logging.getLogger(__name__).warning(
                    "queue_worker_generate_failed",
                    exc_info=e,
                    extra={
                        'email_id': item.email_id,
                        'attempts': attempts,
                    }
                )
                if attempts >= MAX_ATTEMPTS_PER_EMAIL:
                    # Give up on provider for this email; save a minimal local reply and stop re-queueing
                    local_reply = _build_local_fallback(email.subject, email.body)
                    if local_reply:
                        save_auto_response(db, email, local_reply)
                        try:
                            broadcaster.publish("email_updated", f"{{\"id\":{email.id},\"status\":\"responded\"}}")
                        except Exception:
                            pass
                    # reset counter after fallback
                    _attempt_counts.pop(item.email_id, None)
                    continue
                try:
                    # small pause to avoid tight-loop on repeated errors
                    time.sleep(3)
                    _queue.push(item.email_id, email.priority or 'Not urgent')
                except Exception:
                    pass
                continue
            # Save only if we have a non-empty response
            if auto_resp and auto_resp.strip():
                save_auto_response(db, email, auto_resp)
                try:
                    # broadcast update (minimal JSON)
                    broadcaster.publish("email_updated", f"{{\"id\":{email.id},\"status\":\"responded\"}}")
                except Exception:
                    pass
                # success -> clear attempts
                _attempt_counts.pop(item.email_id, None)
            else:
                # Treat empty as failure and re-enqueue with attempt tracking
                attempts = _attempt_counts.get(item.email_id, 0) + 1
                _attempt_counts[item.email_id] = attempts
                logging.getLogger(__name__).warning(
                    "queue_worker_empty_response",
                    extra={
                        'email_id': item.email_id,
                        'attempts': attempts,
                    }
                )
                if attempts >= MAX_ATTEMPTS_PER_EMAIL:
                    local_reply = _build_local_fallback(email.subject, email.body)
                    if local_reply:
                        save_auto_response(db, email, local_reply)
                        try:
                            broadcaster.publish("email_updated", f"{{\"id\":{email.id},\"status\":\"responded\"}}")
                        except Exception:
                            pass
                    _attempt_counts.pop(item.email_id, None)
                else:
                    try:
                        time.sleep(2)
                        _queue.push(item.email_id, email.priority or 'Not urgent')
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


def _build_local_fallback(subject: str, body: str) -> str:
    # Very small, safe local reply if model fails repeatedly
    preview = (body or '').strip().splitlines()
    snippet = (preview[0] if preview else '')
    if len(snippet) > 120:
        snippet = snippet[:120] + '…'
    return (
        "Hi,\n\n"
        "Thanks for your message. We’re looking into this and will get back with a detailed update soon.\n\n"
        f"Subject: {subject or 'Your request'}\n"
        f"Summary: {snippet}\n\n"
        "Best regards,\nSupport Team"
    )
