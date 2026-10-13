from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Relationship, JSON


class AccountType(str, Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    BROKERAGE = "brokerage"
    AGGREGATOR = "aggregator"


class ReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"
    UNRECONCILED_DELTA = "unreconciled_delta"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


# --- Relational Database Models (SQLModel) ---


class TransactionTagLink(SQLModel, table=True):
    """Many-to-Many junction table linking Transactions to Tags."""

    transaction_id: str = Field(foreign_key="transaction.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class Tag(SQLModel, table=True):
    """Normalized Tag table."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    transactions: List["Transaction"] = Relationship(
        back_populates="tags",
        link_model=TransactionTagLink,
        sa_relationship_kwargs={"lazy": "selectin"},
    )


class RawStatement(SQLModel, table=True):
    """Immutable raw statement lake for auditability and re-enrichment."""

    id: str = Field(primary_key=True)
    filename: str
    institution: str
    account_number_masked: str = Field(default="****0000")
    statement_period_start: str
    statement_period_end: str
    starting_balance: float = Field(default=0.0)
    total_credits: float = Field(default=0.0)
    total_debits: float = Field(default=0.0)
    stated_ending_balance: float
    raw_content: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    transactions: List["Transaction"] = Relationship(
        back_populates="statement", sa_relationship_kwargs={"lazy": "selectin"}
    )


class Transaction(SQLModel, table=True):
    """Unified Transaction Model: Acts as Pydantic validation schema AND SQL table."""

    id: Optional[str] = Field(default=None, primary_key=True)
    statement_id: Optional[str] = Field(default=None, foreign_key="rawstatement.id")
    date: str = Field(index=True, description="YYYY-MM-DD")
    raw_description: str
    clean_merchant: str = Field(index=True)
    amount: float = Field(description="Negative for expenses, positive for credits")
    category: str = Field(default="Uncategorized", index=True)
    subcategory: str = Field(default="General")
    leaf_label: Optional[str] = Field(default=None)
    account_type: AccountType = Field(default=AccountType.CHECKING)
    institution: str = Field(default="Unknown")
    confidence: float = Field(default=1.0)
    extracted_entities: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    statement: Optional[RawStatement] = Relationship(back_populates="transactions")
    tags: List[Tag] = Relationship(
        back_populates="transactions",
        link_model=TransactionTagLink,
        sa_relationship_kwargs={"lazy": "selectin"},
    )

    def __init__(self, **data):
        # Convert any string tags passed into Tag objects automatically
        if "tags" in data and data["tags"]:
            converted_tags = []
            for t in data["tags"]:
                if isinstance(t, str):
                    converted_tags.append(Tag(name=t.strip()))
                elif isinstance(t, Tag):
                    converted_tags.append(t)
            data["tags"] = converted_tags

        super().__init__(**data)
        if not self.id:
            fingerprint = f"{self.date}|{self.clean_merchant.upper()}|{self.amount:.2f}|{self.institution.upper()}"
            self.id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]

    def add_tag(self, tag: str | Tag) -> None:
        """Adds a tag to the transaction, avoiding case-insensitive duplicates."""
        name = tag.name if isinstance(tag, Tag) else tag.strip().lower()
        if not name:
            return
        if self.tags is None:
            self.tags = []
        if not any(t.name.lower() == name.lower() for t in self.tags):
            self.tags.append(Tag(name=name))


class MerchantMemory(SQLModel, table=True):
    """Learned merchant memory for <1ms categorization and tag auto-application."""

    pattern: str = Field(primary_key=True)
    clean_merchant: str
    category: str
    subcategory: str
    leaf_label: Optional[str] = None
    default_entities: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    default_tags: List[str] = Field(default_factory=list, sa_type=JSON)
    match_count: int = Field(default=1)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Pure In-Memory API Contracts ---


class StatementSummary(BaseModel):
    institution: str
    account_number_masked: str = "****0000"
    statement_period_start: str
    statement_period_end: str
    starting_balance: float = 0.0
    total_credits: float = 0.0
    total_debits: float = 0.0
    stated_ending_balance: float


class ReconciliationResult(BaseModel):
    status: ReconciliationStatus
    stated_ending_balance: float
    calculated_ending_balance: float
    delta: float
    total_transactions_count: int
    reflection_attempts: int = 0
    unreconciled_reason: Optional[str] = None


class TransactionQuery(BaseModel):
    """Typed Pydantic query model for filtering transactions."""

    category: Optional[str] = None
    tag: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
