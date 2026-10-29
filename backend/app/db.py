import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

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
    # Tests + background workers share one process: an in-memory DB on
    # StaticPool hands a SINGLE connection to every thread, so a TestClient
    # request racing a run_job thread corrupts or locks it (flaky suite).
    # Mirror production instead: one temp-file DB per process, default
    # pooling, one connection per thread; SQLite file locking serializes
    # the tiny test transactions safely.
    import atexit as _atexit
    import tempfile as _tempfile
    _tmp = os.path.join(_tempfile.gettempdir(), f"fieldguard-test-{os.getpid()}.db")
    try:
        os.remove(_tmp)
    except OSError:
        pass
    DATABASE_URL = f"sqlite:///{_tmp}"

    def _cleanup_tmp_db(path: str = _tmp) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    _atexit.register(_cleanup_tmp_db)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
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
