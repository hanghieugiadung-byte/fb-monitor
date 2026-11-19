from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.auth import verify_api_key
from api.deps import get_db
from api.schemas import KeywordBulkCreate, KeywordCreate, KeywordResponse, KeywordUpdate
from storage.models import Keyword

router = APIRouter(
    prefix="/api/keywords",
    tags=["keywords"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/", response_model=List[KeywordResponse])
async def list_keywords(
    session: Session = Depends(get_db),
) -> List[Keyword]:
    """Return all keywords."""
    return session.exec(select(Keyword)).all()


@router.post("/", response_model=KeywordResponse, status_code=status.HTTP_201_CREATED)
async def create_keyword(
    payload: KeywordCreate,
    session: Session = Depends(get_db),
) -> Keyword:
    """Create a single keyword (normalized to lowercase, stripped)."""
    keyword = Keyword(text=payload.text)
    session.add(keyword)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Keyword '{payload.text}' already exists.",
        )
    session.refresh(keyword)
    return keyword


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(
    keyword_id: int,
    session: Session = Depends(get_db),
) -> None:
    """Delete a keyword by id."""
    keyword = session.get(Keyword, keyword_id)
    if not keyword:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    session.delete(keyword)
    session.flush()


@router.post("/{keyword_id}/toggle", response_model=KeywordResponse)
async def toggle_keyword(
    keyword_id: int,
    session: Session = Depends(get_db),
) -> Keyword:
    """Toggle the is_active flag for a keyword."""
    keyword = session.get(Keyword, keyword_id)
    if not keyword:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    keyword.is_active = not keyword.is_active
    session.add(keyword)
    session.flush()
    session.refresh(keyword)
    return keyword


@router.post("/bulk", response_model=List[KeywordResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_keywords(
    payload: KeywordBulkCreate,
    session: Session = Depends(get_db),
) -> List[Keyword]:
    """Create multiple keywords at once. Duplicates are skipped (not an error)."""
    created: List[Keyword] = []
    for text in payload.texts:
        existing = session.exec(select(Keyword).where(Keyword.text == text)).first()
        if existing:
            continue
        kw = Keyword(text=text)
        session.add(kw)
        try:
            session.flush()
            session.refresh(kw)
            created.append(kw)
        except IntegrityError:
            session.rollback()
    return created
