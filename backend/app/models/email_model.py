from sqlalchemy import Column, Integer, String, DateTime, Text
from ..db.database import Base
from datetime import datetime, timezone

class Email(Base):
    __tablename__ = 'emails'
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String, index=True)
    subject = Column(String, index=True)
    body = Column(Text)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sentiment = Column(String, index=True)
    priority = Column(String, index=True)
    auto_response = Column(Text)
    status = Column(String, default='pending', index=True)
    approved_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    source = Column(String, default='unknown', index=True)
    # external_id stores provider-specific unique identifier (e.g., Gmail UID) for stronger dedupe
    external_id = Column(String, nullable=True, index=True)
