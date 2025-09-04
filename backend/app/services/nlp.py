from textblob import TextBlob
from typing import Tuple, List

NEGATIVE_HINTS = ['angry','frustrated','upset','bad','worst','unhappy','disappointed']
PRIORITY_HINTS = ['immediately','critical','cannot access','urgent','down','failure']


def analyze_sentiment(text: str) -> str:
    polarity = TextBlob(text).sentiment.polarity
    if polarity > 0.1:
        return 'Positive'
    if polarity < -0.1:
        return 'Negative'
    # fallback lexical hints
    lowered = text.lower()
    if any(w in lowered for w in NEGATIVE_HINTS):
        return 'Negative'
    return 'Neutral'


def determine_priority(text: str) -> str:
    lowered = text.lower()
    return 'Urgent' if any(w in lowered for w in PRIORITY_HINTS) else 'Not urgent'


def extract_info(text: str):
    import re
    lowered = text.lower()
    phones = re.findall(r"\+?\d[\d\-\s]{7,}\d", text)
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    # simple keyword extraction: take unique nouns-ish tokens length 4..18 excluding stop words
    tokens = re.findall(r"[A-Za-z]{4,18}", lowered)
    stop = set(["this","that","have","with","from","subject","please","thanks","thank","regarding","about","their","there","would","could","should","hello","hi","team","your","issue","request","problem"])
    keywords: List[str] = []
    for t in tokens:
        if t in stop: continue
        if t in keywords: continue
        if any(c.isdigit() for c in t): continue
        keywords.append(t)
        if len(keywords) >= 8: break
    # requested actions: look for imperative verbs (very naive)
    action_patterns = [r"reset", r"refund", r"cancel", r"update", r"upgrade", r"unlock", r"activate", r"deactivate", r"remove", r"add"]
    requested_actions = sorted({m for p in action_patterns for m in re.findall(p, lowered)})
    # sentiment indicator terms actually present
    sentiment_terms = [w for w in NEGATIVE_HINTS if w in lowered]
    return phones, emails, keywords, requested_actions, sentiment_terms
