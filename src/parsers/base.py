from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple, List
from src.models.schemas import Transaction


class BaseStatementParser(ABC):
    """Abstract Strategy interface for parsing statement documents."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Determines if this parser strategy handles the given file."""
        pass

    @abstractmethod
    def parse(self, file_path: Path) -> Tuple[str, List[Transaction]]:
        """
        Extracts raw textual dump and tabular line item transactions.

        Returns:
            Tuple of (raw_text_content, List of Transactions)
        """
        pass
