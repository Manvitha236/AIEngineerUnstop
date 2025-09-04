from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)

def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_ingest_email():
    payload = {
        "sender": "user@example.com",
        "subject": "Support - Cannot access account",
        "body": "Hi team, I cannot access my account immediately. This is critical.",
    "received_at": datetime.now(timezone.utc).isoformat()
    }
    r = client.post('/api/emails/ingest', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['priority'] == 'Urgent'
    assert data['sentiment'] in ['Negative','Neutral','Positive']
    assert 'auto_response' in data
