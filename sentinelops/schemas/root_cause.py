from pydantic import BaseModel, Field


class RootCauseCandidate(BaseModel):
    """Represents one ranked root-cause hypothesis with blended graph and historical-similarity evidence."""

    service: str
    graph_score: float = Field(ge=0.0, le=1.0)
    similarity_score: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    evidence: list[str]
    similar_incident_ids: list[str]


class RootCauseReport(BaseModel):
    """Provides a complete root-cause ranking report for one incident with method transparency."""

    incident_id: str
    candidates: list[RootCauseCandidate]
    top_cause: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    graph_path: list[str]
    analysis_method: str