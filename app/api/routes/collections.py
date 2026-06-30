import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentTenant, DBSession
from app.models.collection import Collection
from app.schemas.collection import (
    CollectionOut,
    CollectionStats,
    CreateCollectionRequest,
)
from app.services.collection_service import create_collection, get_collection_stats

router = APIRouter()


@router.post("", response_model=CollectionOut, status_code=201)
async def create(
    payload: CreateCollectionRequest,
    db: DBSession,
    tenant: CurrentTenant,
):
    collection = await create_collection(
        db,
        tenant_id=tenant.id,
        name=payload.name,
        description=payload.description,
        expected_amount=payload.expected_amount,
        recurrence=payload.recurrence,
    )
    return collection


@router.get("", response_model=list[CollectionOut])
async def list_collections(
    db: DBSession,
    tenant: CurrentTenant,
):
    collections = await db.scalars(
        select(Collection).where(Collection.tenant_id == tenant.id)
    )
    return collections.all()


@router.get("/{collection_id}", response_model=CollectionStats)
async def get_collection(
    collection_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    collection = await db.scalar(
        select(Collection).where(
            Collection.id == collection_id, Collection.tenant_id == tenant.id
        )
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    stats = await get_collection_stats(db, collection)
    return CollectionStats(
        **CollectionOut.model_validate(collection).model_dump(), **stats
    )


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: uuid.UUID,
    db: DBSession,
    tenant: CurrentTenant,
):
    collection = await db.scalar(
        select(Collection).where(
            Collection.id == collection_id, Collection.tenant_id == tenant.id
        )
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection.is_active = False
    db.add(collection)
