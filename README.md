# Support Email AI Assistant

End-to-end sample application: FastAPI backend + React (Vite + TS) frontend for ingesting support emails, prioritizing, generating AI-assisted responses, and monitoring analytics in real-time.

## Features
- Email ingestion with heuristic sentiment & priority classification.
- Background priority queue generates draft auto-responses; optional RAG enrichment with FAISS (persistent store) when ML deps installed.
- Approve / send workflow with status transitions and SSE real-time updates (auto-response, approve, send, manual update).
- Advanced search: free text, domain filter, fuzzy token search, pagination & filters (priority, sentiment, status).
- Knowledge base document endpoints to extend retrieval context.
- Structured JSON logging, request timing & trace IDs.
- API key protection for mutating endpoints (header: `X-API-Key`).
- Auto schema migration for additive columns (SQLite).

## Tech Stack
Backend: FastAPI, SQLAlchemy, Pydantic v2, pytest.
Frontend: React 18, Vite, TypeScript, react-query, Chart.js.
RAG (optional): sentence-transformers + FAISS (install `backend/requirements-ml.txt`).

## Running Locally
```bash
# backend (Python 3.12 recommended)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r backend/requirements-base.txt
uvicorn backend.app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```
Open http://localhost:5173 (or printed Vite URL).

## API Key
Set environment variable `API_KEY=yourkey` before starting backend. Then include header `X-API-Key: yourkey` for POST/PUT endpoints.

## RAG / ML (Optional)
```bash
pip install -r backend/requirements-ml.txt
```
On first load it creates `.rag_store/` with FAISS index & metadata.

## Tests
```bash
pytest -q backend/tests
```

## CI
GitHub Actions workflow (`.github/workflows/ci.yml`) runs backend tests (base deps only) and frontend build on pushes & PRs targeting main/master.

## Future Enhancements
- Add linting (ruff / eslint) to CI.
- Vector search endpoint for querying KB directly.
- AuthN/AuthZ (users / roles) & rate limiting.
- Background IMAP fetcher dedupe & scheduling.

## License
MIT (example project).
