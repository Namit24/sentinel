from collections import defaultdict

import networkx as nx

_EDGE_DEFINITIONS = [
    ("api-gateway", "auth-service"),
    ("api-gateway", "payment-service"),
    ("payment-service", "db-primary"),
    ("payment-service", "cache-service"),
    ("auth-service", "db-primary"),
]

_SEVERITY_TO_SCORE = {
    "CRITICAL": 1.0,
    "ERROR": 0.7,
    "WARN": 0.3,
    "WARNING": 0.3,
}


def build_dependency_graph() -> nx.DiGraph:
    """Builds the static dependency graph once so root-cause ranking has deterministic topology."""

    graph = nx.DiGraph()
    graph.add_edges_from(_EDGE_DEFINITIONS)
    return graph


GRAPH = build_dependency_graph()


def _parse_service_level(item: str) -> tuple[str, str]:
    """Parses optional severity markers from affected-service strings for deterministic base scoring."""

    for delimiter in (":", "|", "#"):
        if delimiter in item:
            service, level = item.split(delimiter, 1)
            return service.strip(), level.strip().upper()
    return item.strip(), "ERROR"


def score_anomalous_nodes(affected_services: list[str], graph: nx.DiGraph) -> dict[str, float]:
    """Assigns base anomaly scores to affected nodes so propagation starts from observed service distress."""

    scores = {node: 0.0 for node in graph.nodes}
    for raw_item in affected_services:
        service, level = _parse_service_level(raw_item)
        if service not in scores:
            continue
        scores[service] = max(scores[service], _SEVERITY_TO_SCORE.get(level, 0.7))
    return scores


def propagate_blame(anomaly_scores: dict[str, float], graph: nx.DiGraph) -> dict[str, float]:
    """Propagates downstream anomaly signal upstream by inverse distance to surface likely origin services."""

    blame = defaultdict(float)
    positive_nodes = [node for node, score in anomaly_scores.items() if score > 0.0]
    for downstream in positive_nodes:
        downstream_score = anomaly_scores[downstream]
        upstream_distances = nx.single_source_shortest_path_length(graph, downstream)
        for upstream, distance in upstream_distances.items():
            if distance == 0:
                blame[upstream] += downstream_score
                continue
            blame[upstream] += downstream_score * (1.0 / distance)

    if not blame:
        return {node: 0.0 for node in graph.nodes}

    maximum = max(blame.values())
    if maximum <= 0.0:
        return {node: 0.0 for node in graph.nodes}
    return {node: round(blame.get(node, 0.0) / maximum, 6) for node in graph.nodes}


def extract_propagation_path(blame_scores: dict[str, float], graph: nx.DiGraph) -> list[str]:
    """Extracts a representative origin-to-impact path to make blame propagation interpretable for users."""

    if not blame_scores:
        return []

    top_blame = max(blame_scores.items(), key=lambda item: item[1])[0]
    positive = {node: score for node, score in blame_scores.items() if score > 0}
    if not positive:
        return [top_blame]

    reverse_graph = graph.reverse(copy=False)
    distances = nx.single_source_shortest_path_length(reverse_graph, top_blame)
    if not distances:
        return [top_blame]
    candidates = [node for node in distances.keys() if node != top_blame]
    if not candidates:
        return [top_blame]
    top_leaf = max(candidates, key=lambda node: (distances[node], positive.get(node, 0.0)))
    try:
        return nx.shortest_path(reverse_graph, source=top_blame, target=top_leaf)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return [top_blame]