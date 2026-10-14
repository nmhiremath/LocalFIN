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

                # Strategy 1: Tabular extraction (for PDFs with vector gridlines)
                tables = page.extract_tables()
                page_txs: List[Transaction] = []
                for table in tables:
                    for row in table:
                        if not row or len(row) < 3:
                            continue

                        cleaned_row = [str(c).strip() if c else "" for c in row]
                        row_str = " ".join(cleaned_row)

                        if any(
                            h in row_str.lower()
                            for h in ["date", "description", "balance", "amount"]
                        ):
                            continue

                        date_match = re.search(
                            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b", row_str
                        )
                        amt_match = re.search(r"(-?\$?\s*[0-9,]+\.[0-9]{2})", row_str)
                        if not date_match or not amt_match:
                            continue

                        date_val = date_match.group(0)
                        amt_raw = amt_match.group(1).replace("$", "").replace(",", "").strip()
                        amount_val = float(amt_raw)

                        desc_candidates = [
                            c
                            for c in cleaned_row
                            if len(c) > 3 and not re.match(r"^[\d\s\$,\.\-]+$", c)
                        ]
                        raw_desc = desc_candidates[0] if desc_candidates else row_str

                        page_txs.append(
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

                # Strategy 2: Line-stream fallback (for borderless text-column bank PDFs)
                if not page_txs and text:
                    for line in text.splitlines():
                        line_str = line.strip()
                        if len(line_str) < 10:
                            continue

                        # Skip header and summary lines
                        lower_line = line_str.lower()
                        if any(
                            s in lower_line
                            for s in [
                                "beginning balance",
                                "ending balance",
                                "starting balance",
                                "total credits",
                                "total debits",
                                "account summary",
                                "page ",
                                "date description",
                            ]
                        ):
                            continue

                        # Detect date near start of line
                        date_match = re.search(
                            r"^(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(?:, \d{4})?)\b",
                            line_str,
                            re.IGNORECASE,
                        ) or re.search(
                            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
                            line_str[:20],
                        )
                        if not date_match:
                            continue

                        # Detect dollar amounts
                        amt_matches = list(re.finditer(r"(-?\$?\s*[0-9,]+\.[0-9]{2})", line_str))
                        if not amt_matches:
                            continue

                        # Transaction amount is typically the first or second numeric column
                        target_amt_match = amt_matches[0]
                        amt_raw = (
                            target_amt_match.group(1).replace("$", "").replace(",", "").strip()
                        )
                        try:
                            amount_val = float(amt_raw)
                        except ValueError:
                            continue

                        # Extract description text between date and amount
                        start_idx = date_match.end()
                        end_idx = target_amt_match.start()
                        if end_idx > start_idx:
                            raw_desc = line_str[start_idx:end_idx].strip()
                        else:
                            raw_desc = line_str[:end_idx].strip()

                        if len(raw_desc) < 2:
                            continue

                        page_txs.append(
                            Transaction(
                                date=date_match.group(0),
                                raw_description=raw_desc,
                                clean_merchant=raw_desc.strip(),
                                amount=amount_val,
                                institution="Bank PDF",
                                account_type=AccountType.CHECKING,
                                raw_metadata={"page": page_idx + 1, "raw_line": line_str},
                            )
                        )

                transactions.extend(page_txs)

        full_raw_text = "\n--- PAGE BREAK ---\n".join(raw_pages)
        return full_raw_text, transactions
