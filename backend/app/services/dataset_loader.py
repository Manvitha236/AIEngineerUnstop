import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from ..models.email_model import Email
from .nlp import analyze_sentiment, determine_priority
from .queue_worker import enqueue_email


DATE_FORMATS = [
    "%d-%m-%Y %H:%M",  # 19-08-2025 00:58
    "%Y-%m-%d %H:%M:%S",  # fallback ISO-like without T
]


def _parse_date(raw: str) -> datetime:
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            # Treat naive as UTC
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    # fallback to now if unparsable
    return datetime.now(timezone.utc)


def load_dataset(
    db: Session,
    csv_path: str,
    *,
    generate_responses: bool = False,
    wipe: bool = True,
) -> Dict[str, Any]:
    """Load (and optionally replace) the emails table from a CSV dataset.

    CSV Columns (header required): sender,subject,body,sent_date
    Unknown / extra columns are ignored.

    Parameters:
        db: SQLAlchemy session.
        csv_path: path to CSV file.
        generate_responses: if True, queue auto-response generation for each loaded email.
        wipe: if True, existing rows are deleted before inserting new ones.
    Returns summary dict.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {csv_path}")

    if wipe:
        db.query(Email).delete()
        db.commit()

    loaded = 0
    errors = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"sender", "subject", "body"}
        missing = required - set(h.lower() for h in reader.fieldnames or [])
        # Normalize header names to lower for safety
        for row in reader:
            try:
                sender = row.get("sender") or row.get("Sender")
                subject = row.get("subject") or row.get("Subject")
                body = row.get("body") or row.get("Body")
                sent_date = row.get("sent_date") or row.get("date") or row.get("received_at")
                if not (sender and subject and body):
                    errors += 1
                    continue
                received_at = _parse_date(sent_date) if sent_date else datetime.now(timezone.utc)
                sentiment = analyze_sentiment(body)
                priority = determine_priority(body)
                email = Email(
                    sender=sender.strip(),
                    subject=subject.strip(),
                    body=body.strip(),
                    received_at=received_at,
                    sentiment=sentiment,
                    priority=priority,
                    auto_response=None,
                    status="pending",
                )
                db.add(email)
                db.flush()  # assign id for queuing
                if generate_responses:
                    enqueue_email(email.id, priority)
                loaded += 1
            except Exception:
                db.rollback()
                errors += 1
            else:
                # don't commit each time (performance) - batch commit every 100
                if loaded % 100 == 0:
                    db.commit()
        db.commit()

    return {
        "loaded": loaded,
        "errors": errors,
        "generate_responses": generate_responses,
        "wipe": wipe,
        "path": str(path.resolve()),
    }
