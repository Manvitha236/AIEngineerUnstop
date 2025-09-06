from typing import List, Dict, Any
import os, logging, concurrent.futures, json, time, threading, random
from concurrent.futures import TimeoutError as FuturesTimeout

try:  # Gemini client (optional now)
    import google.generativeai as genai  # type: ignore
    GEMINI_AVAILABLE = True
except ImportError:  # pragma: no cover
    genai = None  # type: ignore
    GEMINI_AVAILABLE = False

# Track last error states for diagnostics
LAST_GEMINI_ERROR: dict | None = None  # {error_type, error_message, model, ts, ...}
LAST_OR_ERROR: dict | None = None  # OpenRouter provider

# Simple in-process rate limiter for OpenRouter calls
_rate_lock = threading.Lock()
_last_or_ts: float = 0.0  # monotonic seconds
_or_cooldown_until: float = 0.0  # monotonic seconds; after repeated 429s

def test_llm() -> dict:
    """Small probe for currently selected provider."""
    provider = os.getenv('LLM_PROVIDER', 'gemini').lower()
    if provider in {'openrouter','or'}:
        key_ok = bool(os.getenv('OPENROUTER_API_KEY'))
        if not key_ok:
            return {"ok": False, "provider": provider, "reason": "missing_api_key"}
        try:
            txt = _openrouter_call("Ping", test_mode=True)
            return {"ok": True, "provider": provider, "text": (txt or '')[:120], "model": os.getenv('OPENROUTER_MODEL','openrouter/sonoma-sky-alpha')}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "provider": provider, "error_type": type(e).__name__, "error_message": str(e)}
    # gemini path
    if not GEMINI_AVAILABLE:
        return {"ok": False, "provider": provider, "reason": "library_not_installed"}
    if not os.getenv('GOOGLE_API_KEY'):
        return {"ok": False, "provider": provider, "reason": "missing_api_key"}
    model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
    try:
        model = genai.GenerativeModel(model_name)  # type: ignore
        resp = model.generate_content("Ping")  # type: ignore
        txt = _gemini_extract_text(resp).strip() if resp else ""
        return {"ok": True, "provider": provider, "model": model_name, "text": txt[:120]}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "provider": provider, "error_type": type(e).__name__, "error_message": str(e), "model": model_name}

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
    """Generate a reply using configured LLM provider (gemini | openrouter | fallback)."""
    provider = os.getenv('LLM_PROVIDER', 'gemini').lower()
    if provider in {'openrouter','or'}:
        return _generate_openrouter(subject, body, sentiment, priority, rag_results)
    # default to gemini path for any other value (including 'gemini')
    return _generate_gemini(subject, body, sentiment, priority, rag_results)

def _generate_gemini(subject: str, body: str, sentiment: str, priority: str, rag_results: List[tuple]) -> str:
    log = logging.getLogger(__name__)
    context = build_context(rag_results)
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Context:\n{context}\n\n"
        f"Subject: {subject}\n"
        f"Sentiment: {sentiment}\nPriority: {priority}\n"
        f"Customer email:\n{body}\n\nDraft a helpful support reply:".strip()
    )
    global LAST_GEMINI_ERROR
    if os.getenv('GEMINI_FORCE_DISABLE') == '1':
        return _local_fallback_reply(subject, body, sentiment, priority)
    if not GEMINI_AVAILABLE or not os.getenv('GOOGLE_API_KEY'):
        log.warning("Gemini unavailable or missing key; returning sentinel token instead of fallback")
        return "[GEMINI_UNAVAILABLE]"
    backoff_s = float(os.getenv('GEMINI_BACKOFF_SECONDS', '600'))
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

def _openrouter_call(prompt: str, test_mode: bool=False) -> str:
    import httpx
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise RuntimeError('missing OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'openrouter/sonoma-sky-alpha')
    endpoint = os.getenv('OPENROUTER_BASE', 'https://openrouter.ai/api/v1/chat/completions')
    timeout_s = float(os.getenv('OPENROUTER_TIMEOUT', os.getenv('LLM_TIMEOUT', '10')))
    max_tokens = int(os.getenv('OPENROUTER_MAX_TOKENS', '512'))
    min_interval_ms = int(os.getenv('OPENROUTER_MIN_INTERVAL_MS', '1200'))  # ~0.8 QPS by default
    jitter_ms = int(os.getenv('OPENROUTER_JITTER_MS', '120'))
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        # Recommended optional headers for OpenRouter analytics (safe defaults)
        'HTTP-Referer': os.getenv('OPENROUTER_REFERRER','http://localhost'),
        'X-Title': os.getenv('OPENROUTER_APP_NAME','SupportAssistant')
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt if not test_mode else 'Respond with a short pong.'}
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(os.getenv('OPENROUTER_TEMPERATURE','0.4'))
        ,"max_tokens": max_tokens
    }
    log = logging.getLogger(__name__)
    # Short-circuit if we're in a cooldown window (after repeated 429s)
    global _or_cooldown_until
    now_mono = time.monotonic()
    if now_mono < _or_cooldown_until:
        raise RuntimeError('or_http_429_cooldown')
    # Respect a minimal spacing between calls to avoid 429 bursts
    global _last_or_ts
    with _rate_lock:
      now = time.monotonic()
      elapsed_ms = (now - _last_or_ts) * 1000.0
      wait_ms = min_interval_ms - elapsed_ms
      if wait_ms > 0:
          # add small jitter to avoid thundering herd if multiple threads wait
          wait = (wait_ms + random.uniform(0, max(1, jitter_ms))) / 1000.0
          time.sleep(wait)
      _last_or_ts = time.monotonic()

    with httpx.Client(timeout=timeout_s) as client:
        attempts = 0
        while True:
            attempts += 1
            resp = client.post(endpoint, headers=headers, json=payload)
            if resp.status_code == 429:
                # Rate limited. Respect Retry-After if provided, else exponential-ish backoff.
                retry_after = resp.headers.get('retry-after') or resp.headers.get('Retry-After')
                try:
                    backoff_s = float(retry_after) if retry_after is not None else float(os.getenv('OPENROUTER_RATE_LIMIT_BACKOFF_S', '5'))
                except ValueError:
                    backoff_s = float(os.getenv('OPENROUTER_RATE_LIMIT_BACKOFF_S', '5'))
                backoff_s = max(1.0, backoff_s) + random.uniform(0, 0.5)
                log.warning('OpenRouter 429 rate limited; backing off', extra={'backoff_s': round(backoff_s,2), 'attempt': attempts})
                if attempts >= 2:
                    # enter cooldown to avoid hammering for a while
                    cooldown_s = float(os.getenv('OPENROUTER_COOLDOWN_S', '60'))
                    with _rate_lock:
                        _or_cooldown_until = time.monotonic() + max(5.0, cooldown_s)
                    raise RuntimeError('or_http_429: cooldown')
                time.sleep(backoff_s)
                # After sleeping, also space next call a bit
                with _rate_lock:
                    _last_or_ts = time.monotonic()
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f'or_http_{resp.status_code}: {resp.text[:160]}')
            data = resp.json()
            choice = (data.get('choices') or [{}])[0]
            msg = (choice.get('message') or {})
            content = msg.get('content')
            # Some providers may return a list of segments; join any text-like fields
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        for k in ('text', 'content', 'value'):
                            v = part.get(k)
                            if isinstance(v, str) and v.strip():
                                parts.append(v.strip())
                    elif isinstance(part, str) and part.strip():
                        parts.append(part.strip())
                content = "\n".join(parts).strip()
            elif isinstance(content, str):
                content = content.strip()
            else:
                content = ''
            if not content:
                # try refusal or other fields
                ref = msg.get('refusal')
                if isinstance(ref, str) and ref.strip():
                    content = ref.strip()
            return content

def _generate_openrouter(subject: str, body: str, sentiment: str, priority: str, rag_results: List[tuple]) -> str:
    global LAST_OR_ERROR
    log = logging.getLogger(__name__)
    if os.getenv('OPENROUTER_FORCE_DISABLE') == '1':
        return _local_fallback_reply(subject, body, sentiment, priority)
    if not os.getenv('OPENROUTER_API_KEY'):
        return '[OPENROUTER_UNAVAILABLE]'
    context = build_context(rag_results)
    # Truncate overly long body to protect token/credit usage
    max_chars_body = int(os.getenv('OPENROUTER_MAX_BODY_CHARS','4000'))
    orig_body = body
    if len(body) > max_chars_body:
        body = body[:max_chars_body] + "\n...[truncated]"
    prompt = (
        f"Context:\n{context}\n\n"
        f"Subject: {subject}\nSentiment: {sentiment}\nPriority: {priority}\nCustomer email (may be truncated):\n{body}\n\nDraft a helpful support reply.".strip()
    )
    try:
        try:
            reply = _openrouter_call(prompt)
        except RuntimeError as re:
            msg = str(re)
            # Handle credit/token (402) error by aggressive truncation & lower max tokens retry once
            if 'or_http_402' in msg:
                short_body = (orig_body[:1500] + '\n...[hard-truncated]') if len(orig_body) > 1500 else orig_body
                retry_prompt = (
                    f"Subject: {subject}\nSentiment: {sentiment}\nPriority: {priority}\nCustomer email:\n{short_body}\n\nGive a concise helpful support reply (<=120 words)."
                )
                os.environ['OPENROUTER_MAX_TOKENS'] = os.environ.get('OPENROUTER_RETRY_MAX_TOKENS','256')
                reply = _openrouter_call(retry_prompt)
            else:
                raise
        if reply and reply.strip():
            return reply.strip()
        # Retry once with a stricter prompt and lower temperature to avoid empty outputs
        LAST_OR_ERROR = {
            'error_type': 'EmptyOutput',
            'error_message': 'OpenRouter returned empty content on first attempt',
            'model': os.getenv('OPENROUTER_MODEL','openrouter/sonoma-sky-alpha'),
            'ts': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).timestamp(),
        }
        retry_prompt = (
            f"Subject: {subject}\nSentiment: {sentiment}\nPriority: {priority}\n"
            f"Customer email (may be truncated):\n{(orig_body[:1500] + '\n...[hard-truncated]') if len(orig_body) > 1500 else orig_body}\n\n"
            "Write a helpful, plain-text support reply. Do not return an empty response."
        )
        # Temporarily nudge temperature down for retry
        old_temp = os.environ.get('OPENROUTER_TEMPERATURE')
        os.environ['OPENROUTER_TEMPERATURE'] = '0.2'
        try:
            retry_reply = _openrouter_call(retry_prompt)
        finally:
            if old_temp is None:
                os.environ.pop('OPENROUTER_TEMPERATURE', None)
            else:
                os.environ['OPENROUTER_TEMPERATURE'] = old_temp
        if retry_reply and retry_reply.strip():
            return retry_reply.strip()
        # As a last resort, fall back
        if os.getenv('CHAIN_FALLBACK_GEMINI','1')=='1' and os.getenv('GOOGLE_API_KEY') and GEMINI_AVAILABLE:
            try:
                return _generate_gemini(subject, orig_body, sentiment, priority, rag_results)
            except Exception:
                pass
        return _local_fallback_reply(subject, orig_body, sentiment, priority)
    except Exception as e:  # pragma: no cover
        # For transient conditions, bubble up so callers like the queue worker can re-enqueue
        msg = (str(e) or '').lower()
        if any(k in msg for k in ['or_http_429', 'or_http_429_cooldown', 'timeout', 'or_http_5']):
            raise
        LAST_OR_ERROR = {
            'error_type': type(e).__name__,
            'error_message': str(e),
            'model': os.getenv('OPENROUTER_MODEL','openrouter/sonoma-sky-alpha'),
            'ts': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).timestamp()
        }
        log.error('OpenRouter generation failed', exc_info=e, extra={k:v for k,v in LAST_OR_ERROR.items() if k!='prompt_chars'})
        # Optional chained fallback to Gemini if configured
        if os.getenv('CHAIN_FALLBACK_GEMINI','1')=='1' and os.getenv('GOOGLE_API_KEY') and GEMINI_AVAILABLE:
            try:
                return _generate_gemini(subject, orig_body, sentiment, priority, rag_results)
            except Exception:
                pass
        return _local_fallback_reply(subject, orig_body, sentiment, priority) if os.getenv('FALLBACK_LOCAL_REPLY','1')=='1' else '[OPENROUTER_ERROR]'

def ai_diagnostics() -> Dict[str, Any]:  # pragma: no cover
    provider = os.getenv('LLM_PROVIDER','gemini').lower()
    base = {
        'provider': provider,
        'using_local_fallback': os.getenv('FALLBACK_LOCAL_REPLY','1')=='1'
    }
    if provider in {'openrouter','or'}:
        base.update({
            'model': os.getenv('OPENROUTER_MODEL','openrouter/sonoma-sky-alpha'),
            'has_key': bool(os.getenv('OPENROUTER_API_KEY')),
            'last_error': LAST_OR_ERROR,
            'timeout_default_s': float(os.getenv('OPENROUTER_TIMEOUT', os.getenv('LLM_TIMEOUT','10')))
        })
        return base
    # gemini fallback
    base.update({
        'gemini_available': GEMINI_AVAILABLE,
        'has_gemini_key': bool(os.getenv('GOOGLE_API_KEY')),
        'gemini_model': os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
        'last_error': LAST_GEMINI_ERROR,
        'timeout_default_s': float(os.getenv('GEMINI_TIMEOUT', '6')),
        'force_disabled': os.getenv('GEMINI_FORCE_DISABLE') == '1',
        'backoff_seconds': float(os.getenv('GEMINI_BACKOFF_SECONDS','600'))
    })
    return base
