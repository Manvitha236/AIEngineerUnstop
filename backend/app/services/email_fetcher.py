import imaplib, email
from email.header import decode_header
from datetime import datetime, timezone
from typing import List, Dict

SUPPORT_TERMS = ['support','query','request','help']


def fetch_emails(host: str, user: str, password: str, limit: int = 50) -> List[Dict]:
    mails = []
    imap = imaplib.IMAP4_SSL(host)
    imap.login(user, password)
    imap.select('INBOX')
    status, messages = imap.search(None, 'ALL')
    if status != 'OK':
        return mails
    ids = messages[0].split()[-limit:]
    for num in reversed(ids):
        res, msg_data = imap.fetch(num, '(RFC822)')
        if res != 'OK':
            continue
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(msg.get('Subject') or '')[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or 'utf-8', errors='ignore')
                sender = msg.get('From') or ''
                date_hdr = msg.get('Date')
                body = ''
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        disp = str(part.get('Content-Disposition'))
                        if ctype == 'text/plain' and 'attachment' not in disp:
                            charset = part.get_content_charset() or 'utf-8'
                            body += part.get_payload(decode=True).decode(charset, errors='ignore')
                else:
                    charset = msg.get_content_charset() or 'utf-8'
                    body = msg.get_payload(decode=True).decode(charset, errors='ignore') if msg.get_payload(decode=True) else ''
                if any(t in subject.lower() for t in SUPPORT_TERMS):
                    mails.append({
                        'sender': sender,
                        'subject': subject,
                        'body': body,
                        'received_at': date_hdr or datetime.now(timezone.utc).isoformat()
                    })
    imap.logout()
    return mails
