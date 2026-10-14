from typing import Any, cast
from langgraph.graph import StateGraph, START, END
from src.graph.state import AgentState
from src.graph.nodes import (
    ingest_node,
    extract_summary_node,
    reconcile_node,
    reflect_and_correct_node,
    enrich_and_categorize_node,
    persist_node,
)


def route_after_ingest(state: AgentState) -> str:
    """If ingestion failed (e.g. file missing), halt immediately."""
    if state.get("status") == "failed":
        return END
    return "extract_summary"


def route_reconciliation(state: AgentState) -> str:
    """Conditional routing edge implementing circuit breaker logic."""
    if state.get("status") == "reconciled":
        return "enrich_and_categorize"

    if state.get("reflection_attempts", 0) < 2:
        return "reflect_and_correct"

    return "enrich_and_categorize"


def build_financial_statement_graph():
    """Compiles the multi-stage document extraction & reconciliation LangGraph."""
    graph = StateGraph(cast(Any, AgentState))

    # Register Nodes
    graph.add_node("ingest", ingest_node)
    graph.add_node("extract_summary", extract_summary_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("reflect_and_correct", reflect_and_correct_node)
    graph.add_node("enrich_and_categorize", enrich_and_categorize_node)
    graph.add_node("persist", persist_node)

    # Wire Edges
    graph.add_edge(START, "ingest")

    # Conditional edge after ingest: Halt on failure, else continue
    graph.add_conditional_edges(
        "ingest", route_after_ingest, {END: END, "extract_summary": "extract_summary"}
    )

    graph.add_edge("extract_summary", "reconcile")

    # Conditional edge after reconcile: Enrich or Reflect
    graph.add_conditional_edges(
        "reconcile",
        route_reconciliation,
        {
            "enrich_and_categorize": "enrich_and_categorize",
            "reflect_and_correct": "reflect_and_correct",
        },
    )

    graph.add_edge("reflect_and_correct", "reconcile")
    graph.add_edge("enrich_and_categorize", "persist")
    graph.add_edge("persist", END)

    return graph.compile()
