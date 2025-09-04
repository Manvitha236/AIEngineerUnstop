from fastapi.testclient import TestClient
from backend.app.main import app
from datetime import datetime, timezone

client = TestClient(app)


def _seed(subject: str, body: str):
    payload = {
        "sender": "pager@example.com",
        "subject": subject,
        "body": body,
        "received_at": datetime.now(timezone.utc).isoformat()
    }
    return client.post('/api/emails/ingest', json=payload)


def test_pagination_and_shape():
    # Seed more than one page worth (page size we will query = 3)
    markers = ["PAGETEST1 A", "PAGETEST2 B", "PAGETEST3 C", "PAGETEST4 D", "PAGETEST5 E"]
    for m in markers:
        _seed(m, f"Body for {m} urgent immediately")  # add urgency hint so some flagged

    r1 = client.get('/api/emails?limit=3&offset=0')
    assert r1.status_code == 200
    data1 = r1.json()
    for key in ["total", "count", "items", "limit", "offset"]:
        assert key in data1
    assert data1['limit'] == 3
    assert data1['offset'] == 0
    assert data1['count'] <= 3
    assert isinstance(data1['items'], list)

    # Second page
    r2 = client.get('/api/emails?limit=3&offset=3')
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2['offset'] == 3
    # ensure items differ (unless very small dataset)
    if data2['items'] and data1['items']:
        first_page_ids = {e['id'] for e in data1['items']}
        assert not all(e['id'] in first_page_ids for e in data2['items'])


def test_search_filter():
    # Ensure a specific searchable subject exists
    _seed('UniqueSearchMarkerXYZ', 'Content for search indexing')
    rs = client.get('/api/emails?q=UniqueSearchMarkerXYZ')
    assert rs.status_code == 200
    payload = rs.json()
    assert 'items' in payload
    assert any('UniqueSearchMarkerXYZ' in e['subject'] for e in payload['items'])
    # Searching for nonsense should yield zero items (or none containing token)
    rnone = client.get('/api/emails?q=__NO_SUCH_TOKEN__')
    assert rnone.status_code == 200
    none_payload = rnone.json()
    assert 'items' in none_payload
    assert len([e for e in none_payload['items'] if '__NO_SUCH_TOKEN__' in e['subject']]) == 0
