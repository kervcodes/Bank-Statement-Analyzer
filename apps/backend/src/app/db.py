from pathlib import Path

from sqlmodel import Session, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"

engine = create_engine(DATABASE_URL)


def get_session() -> Session:
    return Session(engine)
