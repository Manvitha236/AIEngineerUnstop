from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)

def seed(subject: str, body: str):
    payload = {"sender": "tester@example.com", "subject": subject, "body": body, "received_at": datetime.now(timezone.utc).isoformat()}
    return client.post('/api/emails/ingest', json=payload)

def test_filter_priority_and_sentiment():
    seed('Support - Account locked', 'This is critical and urgent please help immediately.')
    seed('Question - Feedback', 'Just wanted to say you all did a great job.')
    r = client.get('/api/emails?priority=urgent')
    assert r.status_code == 200
    urgent_payload = r.json()
    assert 'items' in urgent_payload
    # priorities currently 'Urgent' or 'Not urgent'
    assert any(e['priority'] == 'Urgent' for e in urgent_payload['items']), f"Got priorities: {[e['priority'] for e in urgent_payload['items']]}"
    r2 = client.get('/api/emails?sentiment=positive')
    assert r2.status_code == 200
    positives_payload = r2.json()
    assert 'items' in positives_payload
    assert isinstance(positives_payload['items'], list)


def test_get_single_email():
    resp = seed('Support - Password Reset', 'Cannot login to my account, urgent assistance needed.')
    email_id = resp.json()['id']
    r = client.get(f'/api/emails/{email_id}')
    assert r.status_code == 200
    data = r.json()
    assert data['id'] == email_id
    assert 'auto_response' in data
