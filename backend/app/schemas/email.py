from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional, List

class ExtractedInfo(BaseModel):
    phone_numbers: List[str] = []
    alt_emails: List[EmailStr] = []
    sentiment: Optional[str] = None
    priority: Optional[str] = None
    keywords: List[str] = []
    requested_actions: List[str] = []
    sentiment_terms: List[str] = []  # positive/negative indicator words found

class EmailBase(BaseModel):
    id: Optional[int]
    sender: EmailStr
    subject: str
    body: str
    received_at: datetime
    source: Optional[str] = None
    external_id: Optional[str] = None

class EmailOut(EmailBase):
    sentiment: Optional[str]
    priority: Optional[str]
    auto_response: Optional[str]
    extracted: ExtractedInfo
    status: Optional[str] = 'pending'

class EmailCreate(BaseModel):
    sender: EmailStr
    subject: str
    body: str
    received_at: datetime
