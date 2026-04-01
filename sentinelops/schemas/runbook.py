from pydantic import BaseModel, Field


class RunbookRecommendation(BaseModel):
    """Represents grounded remediation guidance generated from retrieved runbook evidence."""

    incident_id: str
    top_cause: str
    steps: list[str]
    source_chunks: list[str]
    source_files: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    grounded: bool
    raw_synthesis: str