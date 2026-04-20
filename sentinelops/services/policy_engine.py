from sentinelops.config import settings
from sentinelops.schemas.incident import GroupingOutput
from sentinelops.schemas.policy import PolicyDecision
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation


def build_policy_decision(
    *,
    grouping_output: GroupingOutput,
    report: RootCauseReport,
    runbook: RunbookRecommendation,
) -> PolicyDecision:
    """Evaluates recommendation safety controls suitable for regulated environments with human oversight."""

    status = "ALLOW_HUMAN_REVIEW"
    risk_level = "LOW"
    reviewer_tier = "operator"
    reasons: list[str] = []
    control_flags: list[str] = []

    if settings.POLICY_BLOCK_ON_UNGROUNDED_RUNBOOK and not runbook.grounded:
        status = "BLOCKED"
        risk_level = "CRITICAL"
        reviewer_tier = "incident-commander"
        reasons.append("Runbook recommendation is not grounded in indexed source material.")
        control_flags.append("UNGROUNDED_RUNBOOK")

    if grouping_output.fallback_used:
        status = "ESCALATE_REQUIRED" if status != "BLOCKED" else status
        risk_level = "HIGH" if risk_level != "CRITICAL" else risk_level
        reviewer_tier = "senior-operator" if reviewer_tier == "operator" else reviewer_tier
        reasons.append("LLM grouping fell back to deterministic mode during incident intake.")
        control_flags.append("GROUPING_FALLBACK")

    if report.analysis_method == "graph_only":
        if status == "ALLOW_HUMAN_REVIEW":
            status = "RESTRICTED_REVIEW"
        if risk_level == "LOW":
            risk_level = "MEDIUM"
        reasons.append("Historical incident similarity was unavailable; ranking used graph evidence only.")
        control_flags.append("GRAPH_ONLY_RANKING")

    if report.confidence_score < settings.POLICY_REVIEW_CONFIDENCE_THRESHOLD:
        if status != "BLOCKED":
            status = "ESCALATE_REQUIRED"
        risk_level = "HIGH" if risk_level != "CRITICAL" else risk_level
        reviewer_tier = "senior-operator" if reviewer_tier == "operator" else reviewer_tier
        reasons.append("Root-cause confidence is below the restricted-review threshold.")
        control_flags.append("LOW_ROOT_CAUSE_CONFIDENCE")
    elif report.confidence_score < settings.POLICY_ALLOW_CONFIDENCE_THRESHOLD and status == "ALLOW_HUMAN_REVIEW":
        status = "RESTRICTED_REVIEW"
        if risk_level == "LOW":
            risk_level = "MEDIUM"
        reasons.append("Root-cause confidence is moderate and requires restricted review.")
        control_flags.append("MODERATE_ROOT_CAUSE_CONFIDENCE")

    if runbook.confidence_score < 0.50:
        if status == "ALLOW_HUMAN_REVIEW":
            status = "RESTRICTED_REVIEW"
        if risk_level == "LOW":
            risk_level = "MEDIUM"
        reasons.append("Runbook retrieval confidence is below the preferred threshold.")
        control_flags.append("LOW_RUNBOOK_CONFIDENCE")

    if len(runbook.source_files) < 2:
        if status == "ALLOW_HUMAN_REVIEW":
            status = "RESTRICTED_REVIEW"
        reasons.append("Recommendation is supported by a narrow source set.")
        control_flags.append("NARROW_SOURCE_BASE")

    if report.top_cause == "unknown":
        status = "BLOCKED"
        risk_level = "CRITICAL"
        reviewer_tier = "incident-commander"
        reasons.append("Top cause is unknown; remediation cannot be trusted.")
        control_flags.append("UNKNOWN_TOP_CAUSE")

    confidence = min(report.confidence_score, runbook.confidence_score if runbook.steps else 0.0)
    if not reasons:
        reasons.append("Signals are grounded, confidence is high, and standard human review is sufficient.")

    return PolicyDecision(
        policy_status=status,
        risk_level=risk_level,
        reviewer_tier=reviewer_tier,
        human_action_required=True,
        reasons=reasons,
        control_flags=control_flags,
        confidence_score=max(0.0, min(1.0, confidence)),
    )
