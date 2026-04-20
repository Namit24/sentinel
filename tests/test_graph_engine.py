from sentinelops.services.graph_engine import (
    build_dependency_graph,
    extract_propagation_path,
    propagate_blame,
    score_anomalous_nodes,
)


def test_build_dependency_graph_has_expected_edges() -> None:
    """Verifies static dependency topology matches synthetic environment contract."""

    graph = build_dependency_graph()
    expected = {
        ("api-gateway", "auth-service"),
        ("api-gateway", "payment-service"),
        ("payment-service", "db-primary"),
        ("payment-service", "cache-service"),
        ("auth-service", "db-primary"),
    }
    assert expected.issubset(set(graph.edges()))


def test_score_anomalous_nodes_assigns_expected_base_scores() -> None:
    """Verifies severity markers map to fixed anomaly priors for propagation."""

    graph = build_dependency_graph()
    scores = score_anomalous_nodes(
        ["api-gateway:CRITICAL", "payment-service:ERROR", "cache-service:WARN"],
        graph,
    )
    assert scores["api-gateway"] == 1.0
    assert scores["payment-service"] == 0.7
    assert scores["cache-service"] == 0.3
    assert scores["db-primary"] == 0.0


def test_propagate_blame_ranks_db_primary_highest_for_shared_dependency() -> None:
    """Verifies shared upstream dependency receives highest blame under multi-service anomalies."""

    graph = build_dependency_graph()
    anomaly_scores = {node: 0.0 for node in graph.nodes}
    anomaly_scores["payment-service"] = 0.7
    anomaly_scores["auth-service"] = 0.7

    blame = propagate_blame(anomaly_scores, graph)
    top_service = max(blame.items(), key=lambda item: item[1])[0]
    assert top_service == "db-primary"


def test_extract_propagation_path_returns_non_empty_path() -> None:
    """Verifies path extraction always returns at least one service name for explainability."""

    graph = build_dependency_graph()
    anomaly_scores = score_anomalous_nodes(["api-gateway:CRITICAL"], graph)
    blame = propagate_blame(anomaly_scores, graph)
    path = extract_propagation_path(blame, graph)
    assert len(path) >= 1