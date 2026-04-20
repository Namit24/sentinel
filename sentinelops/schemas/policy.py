from pydantic import BaseModel, Field


class PolicyDecision(BaseModel):
    """Captures whether a recommendation is safe enough for standard review or needs stronger controls."""

    policy_status: str
    risk_level: str
    reviewer_tier: str
    human_action_required: bool = True
    reasons: list[str]
    control_flags: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
