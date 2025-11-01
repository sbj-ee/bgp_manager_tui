# db.py
import os
from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models import Base
from logging_config import get_logger

logger = get_logger(__name__)

DATABASE_URL = "sqlite:///./bgp_sessions.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_new_columns() -> None:
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("bgp_sessions")}

    migrations = [
        ("local_as", "INTEGER NOT NULL DEFAULT 0"),
        ("local_ip", "TEXT NOT NULL DEFAULT ''"),
        ("session_state", "TEXT DEFAULT 'Unknown'"),
        ("description", "TEXT DEFAULT ''"),  # <-- ensures it's present
    ]

    for col_name, col_def in migrations:
        if col_name not in columns:
            logger.info(f"Adding missing column '{col_name}' to bgp_sessions")
            with engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE bgp_sessions ADD COLUMN {col_name} {col_def}")
                )
            logger.info(f"Column '{col_name}' added")


def init_db() -> None:
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    _ensure_new_columns()
    logger.debug("Database schema ensured.")


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        logger.debug("DB session opened.")
        yield db
    except Exception as e:
        logger.error(f"DB error: {e}", exc_info=True)
        raise
    finally:
        db.close()
        logger.debug("DB session closed.")
