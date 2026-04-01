from fastapi import APIRouter

router = APIRouter()


@router.get("/incidents")
async def list_incidents():
    """Stub — will be implemented in Module 1."""
    return {"status": "stub — not yet implemented"}