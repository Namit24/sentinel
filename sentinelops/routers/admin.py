from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.services.vector_store import index_runbooks

router = APIRouter()


@router.post("/admin/index-runbooks")
async def index_runbooks_route(db: AsyncSession = Depends(get_db)) -> dict:
    """Indexes synthetic runbooks and returns idempotent chunk indexing summary."""

    indexed = await index_runbooks(db=db)
    return {"status": "ok", "chunks_indexed": indexed}
