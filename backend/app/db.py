import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool

try:
    from dotenv import load_dotenv
    # Load backend/.env first, then repo-root .env as fallback.
    # override=False so shell exports and test env vars always win.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)
except ImportError:  # python-dotenv not installed (e.g. minimal test env)
    pass

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fieldguard.db")
if DATABASE_URL in ("sqlite://", "sqlite:///:memory:"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
