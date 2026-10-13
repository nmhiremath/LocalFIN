from typing import TypedDict, List, Optional
from src.models.schemas import Transaction, StatementSummary


class AgentState(TypedDict):
    """Complete state object flowing across the LangGraph nodes."""

    file_path: str
    raw_content: str
    summary: Optional[StatementSummary]
    transactions: List[Transaction]
    reconciliation_result: Optional[dict]
    reflection_attempts: int
    status: str
    errors: List[str]


class AgentStateUpdate(AgentState, total=False):
    """Strongly-typed delta updates returned by individual LangGraph nodes."""

    pass
