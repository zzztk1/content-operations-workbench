from __future__ import annotations

from dataclasses import dataclass
from typing import List


RESEARCH_SUBGRAPH_NODES = [
    "research_topic",
    "research_evidence_merge",
]

WRITING_SUBGRAPH_NODES = [
    "write_draft",
    "adapt_platform",
]

VISUAL_SUBGRAPH_NODES = [
    "plan_cover",
    "generate_cover",
    "review_cover_visual",
]

REVIEW_APPROVAL_SUBGRAPH_NODES = [
    "review_structured",
    "review_route",
    "approval_gate",
]

MAIN_GRAPH_NODES = [
    "brief_intake",
    "research_subgraph",
    "writing_subgraph",
    "visual_subgraph",
    "review_approval_subgraph",
    "export",
]


@dataclass(frozen=True)
class GraphLayout:
    version: str
    main_graph_nodes: List[str]
    research_subgraph_nodes: List[str]
    writing_subgraph_nodes: List[str]
    visual_subgraph_nodes: List[str]
    review_approval_subgraph_nodes: List[str]


DEFAULT_GRAPH_LAYOUT = GraphLayout(
    version="v2-draft",
    main_graph_nodes=MAIN_GRAPH_NODES,
    research_subgraph_nodes=RESEARCH_SUBGRAPH_NODES,
    writing_subgraph_nodes=WRITING_SUBGRAPH_NODES,
    visual_subgraph_nodes=VISUAL_SUBGRAPH_NODES,
    review_approval_subgraph_nodes=REVIEW_APPROVAL_SUBGRAPH_NODES,
)
