from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from api.auth import verify_api_key
from api.deps import get_db
from api.schemas import GroupCreate, GroupResponse, GroupUpdate
from storage.models import Group

router = APIRouter(
    prefix="/api/groups",
    tags=["groups"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/", response_model=List[GroupResponse])
async def list_groups(
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    session: Session = Depends(get_db),
) -> List[Group]:
    """Return all groups, optionally filtered by is_active."""
    stmt = select(Group)
    if is_active is not None:
        stmt = stmt.where(Group.is_active == is_active)
    return session.exec(stmt).all()


@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    session: Session = Depends(get_db),
) -> Group:
    """Create a new Facebook group to monitor."""
    group = Group(name=payload.name, fb_url=payload.fb_url)
    session.add(group)
    session.flush()
    session.refresh(group)
    return group


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    session: Session = Depends(get_db),
) -> Group:
    """Return a single group by id."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    payload: GroupUpdate,
    session: Session = Depends(get_db),
) -> Group:
    """Partially update a group."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)
    session.add(group)
    session.flush()
    session.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    session: Session = Depends(get_db),
) -> None:
    """Delete a group and all its associated data."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    session.delete(group)
    session.flush()


@router.post("/{group_id}/toggle", response_model=GroupResponse)
async def toggle_group(
    group_id: int,
    session: Session = Depends(get_db),
) -> Group:
    """Toggle the is_active flag for a group."""
    group = session.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    group.is_active = not group.is_active
    session.add(group)
    session.flush()
    session.refresh(group)
    return group
