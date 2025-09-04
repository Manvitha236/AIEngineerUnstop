from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./emails.db')
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def ensure_schema():  # simple additive migrations for sqlite
    if not DATABASE_URL.startswith('sqlite'):
        return
    with engine.connect() as conn:
        # create tables if not exist
        from ..models import email_model  # noqa: F401
        Base.metadata.create_all(bind=engine)
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('emails')").fetchall()}
        alter_needed = []
        if 'approved_at' not in cols:
            alter_needed.append("ALTER TABLE emails ADD COLUMN approved_at TIMESTAMP NULL")
        if 'sent_at' not in cols:
            alter_needed.append("ALTER TABLE emails ADD COLUMN sent_at TIMESTAMP NULL")
        for stmt in alter_needed:
            try:
                conn.exec_driver_sql(stmt)
            except Exception:
                pass

ensure_schema()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
