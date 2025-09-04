from fastapi.testclient import TestClient
from backend.app.main import app

def test_health_trace_header():
    client = TestClient(app)
    r = client.get('/health')
    assert r.status_code == 200
    # middleware should attach trace id
    # (In tests, call_next runs; header should exist)
    assert 'X-Trace-Id' in r.headers
