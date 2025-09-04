import os
from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)


def test_ingest_requires_key_when_set(monkeypatch):
    monkeypatch.setenv('SUPPORT_API_KEY', 'secret123')
    payload = {
        'sender':'ak@example.com','subject':'Support - Auth','body':'Need help','received_at': datetime.now(timezone.utc).isoformat()
    }
    r = client.post('/api/emails/ingest', json=payload)
    assert r.status_code == 401
    r2 = client.post('/api/emails/ingest', json=payload, headers={'X-API-Key':'secret123'})
    assert r2.status_code == 200
    email_id = r2.json()['id']
    # regenerate without key should fail
    r3 = client.post(f'/api/emails/{email_id}/regenerate')
    assert r3.status_code == 401
    r4 = client.post(f'/api/emails/{email_id}/regenerate', headers={'X-API-Key':'secret123'})
    assert r4.status_code == 200
    # approve & send
    r5 = client.post(f'/api/emails/{email_id}/approve', headers={'X-API-Key':'secret123'})
    assert r5.status_code == 200
    r6 = client.post(f'/api/emails/{email_id}/send', headers={'X-API-Key':'secret123'})
    assert r6.status_code == 200
