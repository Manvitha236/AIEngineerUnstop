from typing import List, Dict, Any
import os, logging, concurrent.futures
from concurrent.futures import TimeoutError as FuturesTimeout

try:  # Gemini mandatory per new simplification
    import google.generativeai as genai  # type: ignore
    GEMINI_AVAILABLE = True
except ImportError:  # pragma: no cover
    genai = None  # type: ignore
    GEMINI_AVAILABLE = False

# Track last Gemini error for diagnostics (must be at module level regardless of import result)
LAST_GEMINI_ERROR: dict | None = None  # {error_type, error_message, model, ts, ...}

def test_gemini() -> dict:
    """Run a tiny test prompt to validate Gemini configuration."""
    if not GEMINI_AVAILABLE:
        return {"ok": False, "reason": "library_not_installed"}
    if not os.getenv('GOOGLE_API_KEY'):
        return {"ok": False, "reason": "missing_api_key"}
    model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
    try:
        model = genai.GenerativeModel(model_name)  # type: ignore
        resp = model.generate_content("Ping")  # type: ignore
        txt = _gemini_extract_text(resp).strip() if resp else ""
        return {"ok": True, "model": model_name, "text": txt[:120]}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error_type": type(e).__name__, "error_message": str(e), "model": model_name}

SYSTEM_PROMPT = (
    "You are a professional, empathetic customer support assistant. "
    "Always respond with concise, actionable guidance."
)

if GEMINI_AVAILABLE:
    _api_key = os.getenv('GOOGLE_API_KEY', '')
    if _api_key:
        try:
            genai.configure(api_key=_api_key)  # type: ignore
        except Exception:
            pass

def build_context(rag_results: List[tuple]) -> str:
    return "\n".join([f"Doc snippet (score={score:.2f}): {text[:300]}" for text, score in rag_results])

def _gemini_extract_text(resp):  # pragma: no cover
    if not resp:
        return ""
    t = getattr(resp, 'text', None)
    if t:
        return t
    try:
        return resp.candidates[0].content.parts[0].text  # type: ignore
    except Exception:
        return ""

def _local_fallback_reply(subject: str, body: str, sentiment: str, priority: str) -> str:
    summary = (body[:240] + '...') if len(body) > 240 else body
    intro = "Thank you for contacting support."
    if 'password' in body.lower():
        intro = "Thanks for reaching out about your password issue."
    action = "We'll investigate and get back to you shortly."
    if priority == 'Urgent':
        action = "We're treating this as high priority and will update you ASAP."
    closing = "Kind regards,\nSupport Team"
    return f"Subject: Re: {subject}\n\n{intro}\n\nI reviewed your message: \n{summary}\n\n{action}\n\n{closing}"

def generate_response(subject: str, body: str, sentiment: str, priority: str, rag_results: List[tuple]) -> str:
    """Generate a reply using ONLY Gemini. No OpenAI, no local fallback."""
    log = logging.getLogger(__name__)
    context = build_context(rag_results)
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Context:\n{context}\n\n"
        f"Subject: {subject}\n"
        f"Sentiment: {sentiment}\nPriority: {priority}\n"
        f"Customer email:\n{body}\n\nDraft a helpful support reply:".strip()
    )
    # Declare global once at function start to avoid SyntaxError on later assignments
    global LAST_GEMINI_ERROR
    # Fast disable path (env toggle or missing key / library)
    if os.getenv('GEMINI_FORCE_DISABLE') == '1':
        return _local_fallback_reply(subject, body, sentiment, priority)
    if not GEMINI_AVAILABLE or not os.getenv('GOOGLE_API_KEY'):
        # Explicit sentinel to make it obvious Gemini isn't configured
        log.warning("Gemini unavailable or missing key; returning sentinel token instead of fallback")
        return "[GEMINI_UNAVAILABLE]"
    # Quota backoff: if last error was ResourceExhausted within backoff window, skip calling API
    backoff_s = float(os.getenv('GEMINI_BACKOFF_SECONDS', '600'))  # default 10 minutes
    if LAST_GEMINI_ERROR and LAST_GEMINI_ERROR.get('error_type') == 'ResourceExhausted':
        from datetime import datetime, timezone
        ts = LAST_GEMINI_ERROR.get('ts')
        if isinstance(ts, (int, float)):
            elapsed = datetime.now(timezone.utc).timestamp() - ts
            if elapsed < backoff_s:
                log.info("Gemini quota backoff active; using fallback", extra={"remaining_s": round(backoff_s - elapsed,1)})
                return _local_fallback_reply(subject, body, sentiment, priority) if os.getenv('FALLBACK_LOCAL_REPLY','1')=='1' else "[GEMINI_QUOTA_BACKOFF]"
    try:
        model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
        model = genai.GenerativeModel(model_name)  # type: ignore
        timeout_s = float(os.getenv('GEMINI_TIMEOUT', '6'))
        resp = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(model.generate_content, prompt)  # type: ignore
            try:
                resp = fut.result(timeout=timeout_s)
            except FuturesTimeout:
                from datetime import datetime, timezone
                LAST_GEMINI_ERROR = {"error_type": "Timeout", "error_message": f">{timeout_s}s", "model": model_name, "ts": datetime.now(timezone.utc).timestamp()}
                log.warning("Gemini generation timeout", extra={"timeout_s": timeout_s, "model": model_name})
                return _local_fallback_reply(subject, body, sentiment, priority) if os.getenv('FALLBACK_LOCAL_REPLY','1')=='1' else "[GEMINI_TIMEOUT]"
        text = _gemini_extract_text(resp).strip()
        if text:
            log.info("Gemini response generated", extra={"model": model_name})
            return text
        log.warning("Gemini returned empty text; returning sentinel token")
        return _local_fallback_reply(subject, body, sentiment, priority) if os.getenv('FALLBACK_LOCAL_REPLY','1')=='1' else "[GEMINI_EMPTY]"
    except Exception as e:  # pragma: no cover
        LAST_GEMINI_ERROR = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "model": os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
            "have_key": bool(os.getenv('GOOGLE_API_KEY')),
            "prompt_chars": len(prompt),
            "ts": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).timestamp()
        }
        log.error("Gemini generation failed", exc_info=e, extra={k: v for k, v in LAST_GEMINI_ERROR.items() if k != 'prompt_chars'})
        return _local_fallback_reply(subject, body, sentiment, priority) if os.getenv('FALLBACK_LOCAL_REPLY','1')=='1' else "[GEMINI_ERROR]"

def ai_diagnostics() -> Dict[str, Any]:  # pragma: no cover
    return {
        "gemini_only": True,
        "gemini_available": GEMINI_AVAILABLE,
        "has_gemini_key": bool(os.getenv('GOOGLE_API_KEY')),
    "gemini_model": os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
    "last_error": LAST_GEMINI_ERROR,
    "timeout_default_s": float(os.getenv('GEMINI_TIMEOUT', '6')),
    "force_disabled": os.getenv('GEMINI_FORCE_DISABLE') == '1',
    "using_local_fallback": os.getenv('FALLBACK_LOCAL_REPLY','1')=='1',
    "backoff_seconds": float(os.getenv('GEMINI_BACKOFF_SECONDS','600'))
    }
