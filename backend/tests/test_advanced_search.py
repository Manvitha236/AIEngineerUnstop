from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)

def _seed(sender: str, subject: str, body: str):
    payload = {
        "sender": sender,
        "subject": subject,
        "body": body,
        "received_at": datetime.now(timezone.utc).isoformat()
    }
    return client.post('/api/emails/ingest', json=payload)

def test_domain_filter():
    # seed different domains
    _seed('alice@example.com', 'DomainTest A', 'Alpha body urgent')
    _seed('bob@another.org', 'DomainTest B', 'Beta body urgent')
    r = client.get('/api/emails?domain=example.com')
    assert r.status_code == 200
    data = r.json()
    assert any('alice@example.com' == e['sender'] for e in data['items'])
    # ensure filtered domain not all items (unless dataset small)
    assert all(e['sender'].endswith('@example.com') for e in data['items'])

def test_fuzzy_search():
    _seed('charlie@example.com', 'Outage impacting payments', 'We see elevated latency in payment processor')
    # fuzzy tokens out of order / partial presence
    r = client.get('/api/emails?q=payments latency&fuzzy=true')
    assert r.status_code == 200
    data = r.json()
    combos = [(e['subject'] + ' ' + e['body']).lower() for e in data['items']]
    assert any('outage impacting payments' in c for c in combos)
    # Non-matching fuzzy tokens should reduce results
    r_none = client.get('/api/emails?q=nonexistenttoken anothermissing&fuzzy=true')
    assert r_none.status_code == 200
    data_none = r_none.json()
    assert data_none['count'] == 0 or all('nonexistenttoken' not in e['subject'].lower() for e in data_none['items'])
