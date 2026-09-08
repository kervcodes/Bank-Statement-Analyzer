from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """Turn on foreign key enforcement for every SQLite connection.

    SQLite defaults PRAGMA foreign_keys to OFF, per connection, which means
    declared foreign keys are silently unenforced: a Transaction referencing a
    statement_id that does not exist will insert and commit without error. This
    listener is registered on the Engine class rather than one engine instance
    so that any engine the app or the tests create is covered -- a fix applied
    only to the engine below would leave the test suite passing against
    unenforced constraints, which is how this went unnoticed the first time.
    """
    # sqlite3.Connection is the only DBAPI in use here, but guard anyway so this
    # stays correct if another database is ever attached in a test.
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # The background worker (app/workers/) writes to the same database file
        # as the request handlers. WAL lets a reader and a writer coexist
        # without blocking; busy_timeout makes a briefly-locked write wait and
        # retry instead of failing immediately with "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


engine = create_engine(DATABASE_URL)


def get_session() -> Session:
    return Session(engine)


def get_db_session():
    """FastAPI dependency: yields a Session, closing it after the request."""
    with get_session() as session:
        yield session
