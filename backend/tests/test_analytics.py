from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)

def test_analytics_summary():
    # ensure at least one email
    payload = {
        "sender": "user@example.com",
        "subject": "Help - login",
        "body": "Need help logging in",
    "received_at": datetime.now(timezone.utc).isoformat()
    }
    client.post('/api/emails/ingest', json=payload)
    r = client.get('/api/analytics/summary')
    assert r.status_code == 200
    data = r.json()
    assert 'total' in data
    assert 'sentiment' in data
    assert 'priority' in data