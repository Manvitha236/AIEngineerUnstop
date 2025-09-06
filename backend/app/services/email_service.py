from sqlalchemy.orm import Session
from typing import List, Optional, Tuple
from sqlalchemy import case, or_
from ..models.email_model import Email
from ..schemas.email import EmailCreate
from datetime import datetime, timedelta, timezone


def create_email(db: Session, payload: EmailCreate, sentiment: str, priority: str, auto_response: Optional[str], source: str='unknown', external_id: Optional[str]=None) -> Email:
    email = Email(
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
    received_at=payload.received_at or datetime.now(timezone.utc),
        sentiment=sentiment,
        priority=priority,
        auto_response=auto_response,
    status='pending',
    source=source,
    external_id=external_id
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    return email

def email_exists(db: Session, sender: str, subject: str, received_at) -> bool:
    return db.query(Email).filter(Email.sender==sender, Email.subject==subject, Email.received_at==received_at).first() is not None

def email_exists_external(db: Session, external_id: str) -> bool:
    return db.query(Email).filter(Email.external_id==external_id).first() is not None


def list_emails(
    db: Session,
    status: Optional[str]=None,
    priority: Optional[str]=None,
    sentiment: Optional[str]=None,
    q_search: Optional[str]=None,
    domain: Optional[str]=None,
    limit: int = 100,
    offset: int = 0,
    source: Optional[str] = None,
    exclude_sources: Optional[List[str]] = None
) -> Tuple[List[Email], int]:
    """List emails with optional filters.

    Parameters:
        status/priority/sentiment: categorical filters
        q_search: free text token(s) search (ILIKE).
        domain: filter by sender email domain (case-insensitive, strips leading '@').
    q_search: simple case-insensitive containment on subject/body/sender.
    """
    q = db.query(Email)
    if status:
        q = q.filter(Email.status==status)
    if priority:
        q = q.filter(Email.priority==priority)
    if sentiment:
        q = q.filter(Email.sentiment==sentiment)
    if domain:
        dom = domain.lower().lstrip('@')
        from sqlalchemy import or_ as _or
        like_exact = f"%@{dom}"
        like_fragment = f"%@%{dom}%"
        q = q.filter(_or(Email.sender.ilike(like_exact), Email.sender.ilike(like_fragment)))
    if q_search:
        like = f"%{q_search.lower()}%"
        q = q.filter((Email.subject.ilike(like)) | (Email.body.ilike(like)) | (Email.sender.ilike(like)))
    if source:
        q = q.filter(Email.source == source)
    if exclude_sources:
        from sqlalchemy import not_, or_, and_
        # Exclude any rows whose source is in the list
        q = q.filter(~Email.source.in_(exclude_sources))

    total = q.count()
    # Order: urgent first, then newest
    priority_order = case((Email.priority == 'Urgent', 0), else_=1)
    items = q.order_by(priority_order, Email.received_at.desc()).offset(offset).limit(limit).all()
    return items, total

def get_email(db: Session, email_id: int) -> Optional[Email]:
    return db.query(Email).filter(Email.id==email_id).first()

def save_auto_response(db: Session, email: Email, text: str, mark_responded: bool=False):
    email.auto_response = text
    if mark_responded:
        email.status = 'responded'
    db.commit()
    db.refresh(email)
    return email


def mark_resolved(db: Session, email_id: int) -> Optional[Email]:
    email = db.query(Email).filter(Email.id == email_id).first()
    if email:
        email.status = 'resolved'
        db.commit()
        db.refresh(email)
    return email

def approve_email(db: Session, email_id: int) -> Optional[Email]:
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        return None
    if email.approved_at is None:
        email.approved_at = datetime.now(timezone.utc)
    if email.status == 'pending' and email.auto_response:
        email.status = 'responded'  # approved but not yet sent
    db.commit(); db.refresh(email)
    return email

def mark_sent(db: Session, email_id: int) -> Optional[Email]:
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        return None
    email.sent_at = datetime.now(timezone.utc)
    email.status = 'resolved'
    db.commit(); db.refresh(email)
    return email


def analytics_summary(db: Session, source: Optional[str] = None, exclude_sources: Optional[List[str]] = None):
    base = db.query(Email)
    if source:
        base = base.filter(Email.source == source)
    if exclude_sources:
        base = base.filter(~Email.source.in_(exclude_sources))

    total = base.count()
    now = datetime.now(timezone.utc)
    last_24 = base.filter(Email.received_at >= now - timedelta(hours=24)).count()
    by_sentiment = {s: base.filter(Email.sentiment==s).count() for s in ['Positive','Neutral','Negative']}
    by_priority = {p: base.filter(Email.priority==p).count() for p in ['Urgent','Not urgent']}
    resolved = base.filter(Email.status=='resolved').count()
    pending = base.filter(Email.status=='pending').count()
    return {
        'total': total,
        'last_24h': last_24,
        'sentiment': by_sentiment,
        'priority': by_priority,
        'resolved': resolved,
        'pending': pending
    }
