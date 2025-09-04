import logging, os, json, sys

LOG_FORMAT_KEYS = [
    "time","level","msg","trace_id","method","path","status","duration_ms"
]

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover (formatting)
        base = {
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        # Merge any extra attributes we care about
        for k in ["trace_id","method","path","status","duration_ms"]:
            if hasattr(record, k):
                base[k] = getattr(record, k)
        return json.dumps(base, ensure_ascii=False)

def init_logging():
    level = os.getenv("LOG_LEVEL","INFO").upper()
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = False