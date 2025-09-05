"""Unified email retrieval providers.

Supported PROVIDER env values (EMAIL_PROVIDER):
  - imap (default): use generic IMAP credentials (EMAIL_IMAP_HOST, USER, PASSWORD)
  - gmail: IMAP against Gmail with optional label filtering (EMAIL_GMAIL_LABEL)
  - outlook: Microsoft Graph API (requires token); currently a stub with clear error if not configured
  - smtp-inbox: placeholder for custom SMTP sink / local test mailbox directory

Each provider returns a list of dicts with keys: sender, subject, body, received_at (ISO string)
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Dict
import os
import logging
from dataclasses import dataclass
import socket

@dataclass
class GmailDiag:
    last_error: str | None = None
    last_login_ok: bool | None = None
    last_fetch_count: int = 0
    last_label: str | None = None
    last_ts: str | None = None

gmail_diag = GmailDiag()

from .email_fetcher import fetch_emails as generic_imap_fetch

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def fetch_from_imap(limit: int) -> List[Dict]:
    host = os.getenv('EMAIL_IMAP_HOST')
    user = os.getenv('EMAIL_IMAP_USER')
    pwd = os.getenv('EMAIL_IMAP_PASSWORD')
    if not (host and user and pwd):
        return []
    return generic_imap_fetch(host, user, pwd, limit=limit)


def fetch_from_gmail(limit: int) -> List[Dict]:  # Gmail over IMAP with optional label search (uses UID for dedupe)
    # Gmail IMAP host is fixed; label search uses X-GM-RAW if provided.
    import imaplib, email
    from email.header import decode_header
    if os.getenv('GMAIL_DEBUG') == '1':  # protocol-level debug
        try:
            imaplib.Debug = 4
        except Exception:
            pass

    user = os.getenv('GMAIL_USER') or os.getenv('EMAIL_IMAP_USER')
    pwd = os.getenv('GMAIL_APP_PASSWORD') or os.getenv('EMAIL_IMAP_PASSWORD')
    label = os.getenv('EMAIL_GMAIL_LABEL')  # e.g. "Support" or "INBOX"
    if not (user and pwd):
        gmail_diag.last_error = "missing_credentials"
        gmail_diag.last_login_ok = False
        return []
    host = 'imap.gmail.com'
    mails: List[Dict] = []
    try:
        # Connection-specific timeout (avoid changing global default which broke other sockets/SSE)
        try:
            to = float(os.getenv('GMAIL_TIMEOUT', '8'))
        except Exception:
            to = 8.0
        from datetime import datetime, timezone
        gmail_diag.last_ts = datetime.now(timezone.utc).isoformat()
        # imaplib.IMAP4_SSL in Py3.12 accepts 'timeout' param; fallback if not
        try:
            imap = imaplib.IMAP4_SSL(host, timeout=to)
        except TypeError:  # older python
            imap = imaplib.IMAP4_SSL(host)
            try:
                imap.sock.settimeout(to)
            except Exception:
                pass
        imap.login(user, pwd)
        gmail_diag.last_login_ok = True
        imap.select(label or 'INBOX')
        status, data = imap.uid('search', None, 'ALL')
        if status != 'OK':
            gmail_diag.last_error = f"search_failed_status_{status}"
            return []
        uids = data[0].split()[-limit:]
        for uid in reversed(uids):  # iterate oldest->newest among slice
            res, msg_data = imap.uid('fetch', uid, '(RFC822)')
            if res != 'OK':
                continue
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg.get('Subject') or '')[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or 'utf-8', errors='ignore')
                    sender = msg.get('From') or ''
                    date_hdr = msg.get('Date') or _now_iso()
                    body = ''
                    html_candidate = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            disp = str(part.get('Content-Disposition'))
                            if ctype == 'text/plain' and 'attachment' not in disp:
                                charset = part.get_content_charset() or 'utf-8'
                                try:
                                    body += part.get_payload(decode=True).decode(charset, errors='ignore')
                                except Exception:
                                    pass
                            elif ctype == 'text/html' and 'attachment' not in disp and not body:
                                # keep as fallback only if no plain text collected
                                try:
                                    html_candidate = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                                except Exception:
                                    pass
                    else:
                        charset = msg.get_content_charset() or 'utf-8'
                        payload = msg.get_payload(decode=True)
                        if payload:
                            try:
                                body = payload.decode(charset, errors='ignore')
                            except Exception:
                                body = ''
                    import re, html as _html
                    # If no text/plain but we have html part -> strip and use
                    if not body and html_candidate:
                        txt = html_candidate
                        txt = re.sub(r'<\s*br\s*/?>', '\n', txt, flags=re.I)
                        txt = re.sub(r'</(p|div|tr|table|li|h[1-6])\s*>', '\n', txt, flags=re.I)
                        txt = re.sub(r'<[^>]+>', ' ', txt)
                        txt = _html.unescape(re.sub(r'\s+', ' ', txt)).strip()
                        body = txt
                    # Some senders wrongly embed full HTML inside text/plain; broaden detection
                    if body and '<' in body and '>' in body:
                        tag_matches = re.findall(r'<[^>]{1,200}>', body)
                        if tag_matches:
                            tag_ratio = len(''.join(tag_matches)) / max(1, len(body))
                            html_markers = 0
                            for mk in ('<html','<body','<table','</tr','</td','<div','<!DOCTYPE','<span','<p','style=','class='):
                                if mk.lower() in body.lower():
                                    html_markers += 1
                            # Strip if clear HTML structure OR density high
                            if html_markers >= 2 or len(tag_matches) > 8 or tag_ratio > 0.04:
                                txt = body
                                txt = re.sub(r'<\s*br\s*/?>', '\n', txt, flags=re.I)
                                txt = re.sub(r'</(p|div|tr|table|li|h[1-6])\s*>', '\n', txt, flags=re.I)
                                txt = re.sub(r'<[^>]+>', ' ', txt)
                                txt = _html.unescape(re.sub(r'\s+', ' ', txt)).strip()
                                if txt and len(txt) > 5:
                                    body = txt
                    mails.append({
                        'sender': sender,
                        'subject': subject,
                        'body': body,
                        'received_at': date_hdr,
                        'external_id': uid.decode(errors='ignore') if isinstance(uid, bytes) else str(uid)
                    })
        imap.logout()
        gmail_diag.last_fetch_count = len(mails)
        gmail_diag.last_label = label or 'INBOX'
        gmail_diag.last_error = None
    except Exception as e:
        logging.getLogger(__name__).warning(
            "gmail_fetch_error",
            exc_info=e,
            extra={"error_type": type(e).__name__, "error_message": str(e)[:500]}
        )
        gmail_diag.last_error = type(e).__name__ + ":" + str(e)
        gmail_diag.last_login_ok = False
        return []
    return mails


def fetch_from_outlook(limit: int) -> List[Dict]:
    """Fetch emails via Microsoft Graph.
    Requirements (not enforced here): OUTLOOK_TENANT_ID, OUTLOOK_CLIENT_ID, OUTLOOK_CLIENT_SECRET, OUTLOOK_USER_ID.
    This is a stub to illustrate extension; returns [] if token env not present.
    """
    token = os.getenv('OUTLOOK_ACCESS_TOKEN')  # In production you'd implement OAuth client credential / refresh.
    if not token:
        return []
    # Minimal example (no external call due to offline environment):
    return []


def fetch_from_smtp_sink(limit: int) -> List[Dict]:
    """Placeholder for a custom SMTP sink (e.g., MailHog / local directory)."""
    path = os.getenv('SMTP_SINK_DIR')
    if not path or not os.path.isdir(path):
        return []
    mails: List[Dict] = []
    try:
        files = sorted([f for f in os.listdir(path) if f.endswith('.eml')])[-limit:]
        import email
        for fname in files:
            with open(os.path.join(path, fname), 'rb') as fh:
                msg = email.message_from_bytes(fh.read())
            sender = msg.get('From') or ''
            subject = msg.get('Subject') or ''
            body = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body += part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
            else:
                payload = msg.get_payload(decode=True)
                body = payload.decode('utf-8', errors='ignore') if payload else ''
            mails.append({'sender': sender,'subject': subject,'body': body,'received_at': _now_iso()})
    except Exception:
        return []
    return mails


PROVIDERS = {
    'imap': fetch_from_imap,
    'gmail': fetch_from_gmail,
    'outlook': fetch_from_outlook,
    'smtp-inbox': fetch_from_smtp_sink,
    'demo': lambda limit: [],  # demo mode -> no external fetch
}

# Runtime override (None means use env)
RUNTIME_PROVIDER_OVERRIDE: str | None = None

def set_runtime_provider(provider: str | None):
    global RUNTIME_PROVIDER_OVERRIDE
    if provider is None:
        RUNTIME_PROVIDER_OVERRIDE = None
    else:
        provider = provider.lower()
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'")
        RUNTIME_PROVIDER_OVERRIDE = provider
    # log change for debugging stuck mode issues
    import logging
    logging.getLogger(__name__).info("runtime_provider_set", extra={"provider": RUNTIME_PROVIDER_OVERRIDE})

def get_runtime_provider() -> str:
    return (RUNTIME_PROVIDER_OVERRIDE or os.getenv('EMAIL_PROVIDER', 'imap')).lower()

def fetch_any(limit: int = 25) -> List[Dict]:
    provider = get_runtime_provider()
    fn = PROVIDERS.get(provider, fetch_from_imap)
    return fn(limit)
