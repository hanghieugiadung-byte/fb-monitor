"""FastAPI generator dependency that wraps storage.database.get_session."""
from typing import Generator
from sqlmodel import Session
from storage.database import engine


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLModel Session for use with FastAPI Depends()."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
