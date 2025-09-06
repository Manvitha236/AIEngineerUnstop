from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..services.email_service import analytics_summary
from ..services.retrievers import get_runtime_provider
from fastapi import Query
from ..services.auto_responder import ai_diagnostics, generate_response
from fastapi import Query

router = APIRouter()

@router.get("/summary")
def summary(db: Session = Depends(get_db), source: str | None = Query(None)):
    runtime = get_runtime_provider()
    src = source
    exclude = None
    if not src and runtime == 'gmail':
        exclude = ['demo', 'unknown']
    return analytics_summary(db, source=src, exclude_sources=exclude)

@router.get("/ai")
def ai_status():
    return ai_diagnostics()

@router.get("/ai/test")
def ai_test(prompt: str = Query("Test connectivity")):
    # Use minimal wrapper to see raw provider output (truncated) or fallback
    txt = generate_response("Diagnostic", prompt, "Neutral", "Not urgent", [])
    # Do not expose keys; just return length and snippet
    return {"snippet": txt[:220], "length": len(txt)}
