from typing import List, Optional
from typing_extensions import TypedDict
from src.models.schemas import Transaction, StatementSummary


class AgentState(TypedDict):
    """Complete state object flowing across the LangGraph nodes."""

    file_path: str
    raw_content: Optional[str]
    summary: Optional[StatementSummary]
    transactions: List[Transaction]
    reconciliation_result: Optional[dict]
    reflection_attempts: int
    status: str
    errors: List[str]


class AgentStateUpdate(TypedDict, total=False):
    """Strongly-typed delta updates returned by individual LangGraph nodes."""

    file_path: str
    raw_content: Optional[str]
    summary: Optional[StatementSummary]
    transactions: List[Transaction]
    reconciliation_result: Optional[dict]
    reflection_attempts: int
    status: str
    errors: List[str]
