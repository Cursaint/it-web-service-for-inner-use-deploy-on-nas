import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Automatically load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Lightweight fallback parser if python-dotenv is not installed
    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.is_file():
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _key, _val = _line.split("=", 1)
                _key = _key.strip()
                _val = _val.strip().strip("'\"")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/it_service"
)
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_connection():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=5
    )
