import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import func
from sqlmodel import SQLModel, Session, create_engine, select

from src.models.schemas import (
    Transaction,
    RawStatement,
    Tag,
    TransactionTagLink,
    MerchantMemory,
    StatementSummary,
    TransactionQuery,
)


from src.config import DEFAULT_DB_PATH


class DatabaseManager:
    """Enterprise SQLModel persistence engine managing raw statements,
    normalized transactions, Many-to-Many relational tags, and learned merchant memory.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self._init_db()

    def _init_db(self):
        """Creates all tables and indexes automatically from SQLModel metadata."""
        SQLModel.metadata.create_all(self.engine)

    def insert_raw_statement(
        self, summary: StatementSummary, raw_content: str, filename: str
    ) -> str:
        """Stores the untouched raw statement text and balance header for forensic auditing."""
        stmt_id = (
            f"{summary.institution}_{summary.statement_period_start}_{summary.statement_period_end}"
        )
        stmt = RawStatement(
            id=stmt_id,
            filename=filename,
            institution=summary.institution,
            account_number_masked=summary.account_number_masked,
            statement_period_start=summary.statement_period_start,
            statement_period_end=summary.statement_period_end,
            starting_balance=summary.starting_balance,
            total_credits=summary.total_credits,
            total_debits=summary.total_debits,
            stated_ending_balance=summary.stated_ending_balance,
            raw_content=raw_content,
        )
        with Session(self.engine, expire_on_commit=False) as session:
            session.merge(stmt)
            session.commit()
        return stmt_id

    def insert_transactions(
        self, txs: List[Transaction], statement_id: Optional[str] = None
    ) -> Tuple[int, int]:
        """Inserts transactions with primary-key deduplication and resolves tags via junction table.

        Returns:
            Tuple of (inserted_count, duplicate_count)
        """
        inserted_count = 0
        duplicate_count = 0

        with Session(self.engine, expire_on_commit=False) as session:
            for tx in txs:
                if statement_id:
                    tx.statement_id = statement_id

                existing = session.get(Transaction, tx.id)
                if not existing:
                    # Resolve tags in the current session
                    tags_to_attach = []
                    for t in tx.tags or []:
                        tag_name = t.name.strip() if hasattr(t, "name") else str(t).strip()
                        db_tag = session.exec(
                            select(Tag).where(func.lower(Tag.name) == tag_name.lower())
                        ).first()
                        if not db_tag:
                            db_tag = Tag(name=tag_name)
                            session.add(db_tag)
                            session.flush()
                        tags_to_attach.append(db_tag)

                    tx.tags = tags_to_attach
                    session.add(tx)
                    inserted_count += 1
                else:
                    duplicate_count += 1
            session.commit()

        return inserted_count, duplicate_count

    def get_or_create_tag(self, tag_name: str) -> Tag:
        """Looks up an existing tag (case-insensitive) or creates a new one."""
        clean_name = tag_name.strip()
        with Session(self.engine, expire_on_commit=False) as session:
            statement = select(Tag).where(func.lower(Tag.name) == clean_name.lower())
            tag = session.exec(statement).first()
            if not tag:
                tag = Tag(name=clean_name)
                session.add(tag)
                session.commit()
                session.refresh(tag)
            return tag

    def add_tag_to_transactions(self, tx_ids: List[str], tag_name: str):
        """Associates transaction IDs with a tag name via the Many-to-Many junction table."""
        tag = self.get_or_create_tag(tag_name)
        with Session(self.engine, expire_on_commit=False) as session:
            for tx_id in tx_ids:
                link = session.get(TransactionTagLink, (tx_id, tag.id))
                if not link:
                    session.add(TransactionTagLink(transaction_id=tx_id, tag_id=tag.id))
            session.commit()

    def rename_tag(self, old_name: str, new_name: str) -> bool:
        """Atomically renames a tag across all linked transactions in 1 query."""
        with Session(self.engine, expire_on_commit=False) as session:
            statement = select(Tag).where(func.lower(Tag.name) == old_name.strip().lower())
            tag = session.exec(statement).first()
            if tag:
                tag.name = new_name.strip()
                session.add(tag)
                session.commit()
                return True
            return False

    def get_spending_by_tag(self, tag_name: str) -> float:
        """Calculates total spend for a tag using a type-safe SQLModel join."""
        with Session(self.engine, expire_on_commit=False) as session:
            statement = (
                select(func.sum(Transaction.amount))
                .join(TransactionTagLink)
                .join(Tag)
                .where(func.lower(Tag.name) == tag_name.strip().lower())
                .where(Transaction.amount < 0)
            )
            total = session.exec(statement).first() or 0.0
            return round(abs(total), 2)

    def get_tags_for_transaction(self, tx_id: str) -> List[str]:
        """Retrieves all tag names associated with a specific transaction."""
        with Session(self.engine, expire_on_commit=False) as session:
            statement = (
                select(Tag.name)
                .join(TransactionTagLink)
                .where(TransactionTagLink.transaction_id == tx_id)
                .order_by(Tag.name)
            )
            return list(session.exec(statement).all())

    def lookup_merchant_memory(self, raw_description: str) -> Optional[Dict[str, Any]]:
        """Scans the learned merchant memory cache for an existing categorization rule (<1ms)."""
        raw_upper = raw_description.upper()
        with Session(self.engine, expire_on_commit=False) as session:
            statement = select(MerchantMemory).order_by(func.length(MerchantMemory.pattern).desc())
            memories = session.exec(statement).all()

            for memory in memories:
                matched = False
                try:
                    if re.search(memory.pattern, raw_description, re.IGNORECASE):
                        matched = True
                except Exception:
                    pass
                if not matched and memory.pattern.upper() in raw_upper:
                    matched = True

                if matched:
                    memory.match_count += 1
                    session.add(memory)
                    session.commit()
                    return {
                        "pattern": memory.pattern,
                        "clean_merchant": memory.clean_merchant,
                        "category": memory.category,
                        "subcategory": memory.subcategory,
                        "leaf_label": memory.leaf_label,
                        "entities": memory.default_entities,
                        "tags": memory.default_tags,
                    }
        return None

    def save_merchant_memory(
        self,
        pattern: Optional[str] = None,
        clean_merchant: Optional[str] = None,
        category: str = "Uncategorized",
        subcategory: str = "General",
        leaf_label: Optional[str] = None,
        entities: Optional[Dict[str, Any]] = None,
        default_tags: Optional[List[str]] = None,
        raw_pattern: Optional[str] = None,
        normalized_name: Optional[str] = None,
    ):
        """Learns and saves a recurring merchant rule along with auto-applicable tags."""
        pat = pattern or raw_pattern or ""
        name = clean_merchant or normalized_name or pat
        memory = MerchantMemory(
            pattern=pat,
            clean_merchant=name,
            category=category,
            subcategory=subcategory,
            leaf_label=leaf_label,
            default_entities=entities or {},
            default_tags=default_tags or [],
        )
        with Session(self.engine, expire_on_commit=False) as session:
            session.merge(memory)
            session.commit()

    def get_spending_summary(self) -> Dict[str, float]:
        """Calculates total expense spend grouped by category."""
        with Session(self.engine, expire_on_commit=False) as session:
            statement = (
                select(Transaction.category, func.sum(Transaction.amount))
                .where(Transaction.amount < 0)
                .group_by(Transaction.category)
            )
            results = session.exec(statement).all()
            return {cat: round(abs(total), 2) for cat, total in results}

    def get_transactions(self, query: TransactionQuery) -> List[Transaction]:
        """Type-safe dynamic querying across transactions using Pydantic query model."""
        with Session(self.engine, expire_on_commit=False) as session:
            statement = select(Transaction)
            if query.category:
                statement = statement.where(Transaction.category == query.category)
            if query.start_date:
                statement = statement.where(Transaction.date >= query.start_date)
            if query.end_date:
                statement = statement.where(Transaction.date <= query.end_date)
            if query.min_amount is not None:
                statement = statement.where(Transaction.amount >= query.min_amount)
            if query.max_amount is not None:
                statement = statement.where(Transaction.amount <= query.max_amount)
            if query.tag:
                statement = (
                    statement.join(TransactionTagLink)
                    .join(Tag)
                    .where(func.lower(Tag.name) == query.tag.strip().lower())
                )
            return list(session.exec(statement).all())
