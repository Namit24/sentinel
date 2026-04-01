from fastapi import APIRouter

router = APIRouter()


@router.post("/ingest")
async def ingest_telemetry():
    """Stub — will be implemented in Module 1."""
    return {"status": "stub — not yet implemented"}