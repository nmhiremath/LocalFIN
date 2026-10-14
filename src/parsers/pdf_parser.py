import re
from pathlib import Path
from typing import Tuple, List
import pdfplumber

from src.models.schemas import Transaction, AccountType
from src.parsers.base import BaseStatementParser


class PDFPlumberStatementParser(BaseStatementParser):
    """Extracts raw text streams and tabular transactions using pdfplumber."""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"

    def parse(self, file_path: Path) -> Tuple[str, List[Transaction]]:
        transactions: List[Transaction] = []
        raw_pages: List[str] = []

        with pdfplumber.open(file_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                raw_pages.append(text)

                # Extract table structures
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 3:
                            continue

                        cleaned_row = [str(c).strip() if c else "" for c in row]
                        row_str = " ".join(cleaned_row)

                        # Skip header lines
                        if any(
                            h in row_str.lower()
                            for h in ["date", "description", "balance", "amount"]
                        ):
                            continue

                        # Detect Date column (MM/DD/YYYY, YYYY-MM-DD, MM/DD)
                        date_match = re.search(
                            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b", row_str
                        )
                        if not date_match:
                            continue

                        # Detect Dollar Amount
                        amt_match = re.search(r"(-?\$?\s*[0-9,]+\.[0-9]{2})", row_str)
                        if not amt_match:
                            continue

                        date_val = date_match.group(0)
                        amt_raw = amt_match.group(1).replace("$", "").replace(",", "").strip()
                        amount_val = float(amt_raw)

                        # Longest non-numeric text is the raw description
                        desc_candidates = [
                            c
                            for c in cleaned_row
                            if len(c) > 3 and not re.match(r"^[\d\s\$,\.\-]+$", c)
                        ]
                        raw_desc = desc_candidates[0] if desc_candidates else row_str

                        transactions.append(
                            Transaction(
                                date=date_val,
                                raw_description=raw_desc,
                                clean_merchant=raw_desc.strip(),
                                amount=amount_val,
                                institution="Bank PDF",
                                account_type=AccountType.CHECKING,
                                raw_metadata={"page": page_idx + 1, "raw_cells": cleaned_row},
                            )
                        )

        full_raw_text = "\n--- PAGE BREAK ---\n".join(raw_pages)
        return full_raw_text, transactions
