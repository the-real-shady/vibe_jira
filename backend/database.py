import os
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DB_URL = os.getenv("DB_URL", "sqlite:///./data/agentboard.db")

# SQLite needs check_same_thread=False for use across threads
connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DB_URL,
    connect_args=connect_args,
    echo=False,
)


def init_db() -> None:
    """Create all tables and enable WAL mode for SQLite."""
    # Ensure data directory exists
    if DB_URL.startswith("sqlite:///./"):
        db_path = DB_URL.replace("sqlite:///./", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    SQLModel.metadata.create_all(engine)

    # Enable WAL mode for better concurrent read performance
    if DB_URL.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a DB session."""
    with Session(engine) as session:
        yield session
