import re
from pathlib import Path
from typing import Tuple, List, Optional
import pdfplumber

from src.models.schemas import Transaction, AccountType
from src.parsers.base import BaseStatementParser


class PDFPlumberStatementParser(BaseStatementParser):
    """Extracts raw text streams and tabular transactions using pdfplumber with automated header and sign detection."""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"

    @staticmethod
    def _detect_institution(text: str, filename: str) -> str:
        haystack = f"{filename} {text[:3000]}".lower()
        if "chase" in haystack or "jpmorgan" in haystack:
            return "Chase"
        elif "discover" in haystack:
            return "Discover"
        elif "citi" in haystack:
            return "Citi"
        elif "capital one" in haystack:
            return "Capital One"
        elif "bank of america" in haystack or "bofa" in haystack:
            return "Bank of America"
        elif "wells fargo" in haystack:
            return "Wells Fargo"
        elif "american express" in haystack or "amex" in haystack:
            return "American Express"
        return "Bank PDF"

    @staticmethod
    def _detect_account_type(text: str) -> AccountType:
        lower = text[:4000].lower()
        cc_signals = [
            "credit card",
            "payment due date",
            "minimum payment",
            "credit limit",
            "card ending in",
            "cardmember",
            "new balance",
            "cash advance",
            "rewards summary",
        ]
        if any(sig in lower for sig in cc_signals):
            return AccountType.CREDIT_CARD
        return AccountType.CHECKING

    @staticmethod
    def _detect_masked_account(text: str) -> Optional[str]:
        m = re.search(
            r"(?:account|card|acct)\s*(?:number|ending|#)?(?:\s+in)?\s*[:#]?\s*[\*Xx\s]*(\d{4})",
            text[:4000],
            re.IGNORECASE,
        )
        if m:
            return f"****{m.group(1)}"
        return None

    @staticmethod
    def _detect_year(text: str) -> str:
        m = re.search(
            r"(?:statement\s+(?:period|date|closing)|closing\s+date|cycle|period\s+from).*?(202[4-9])",
            text[:4000],
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        m_generic = re.search(r"(202[4-9])", text[:3000])
        return m_generic.group(1) if m_generic else "2026"

    @staticmethod
    def _normalize_date(raw_date: str, year: str) -> str:
        m = re.match(r"^(\d{1,2})/(\d{1,2})$", raw_date.strip())
        if m:
            return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        m_full = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw_date.strip())
        if m_full:
            return f"{m_full.group(3)}-{int(m_full.group(1)):02d}-{int(m_full.group(2)):02d}"
        return raw_date

    @staticmethod
    def _normalize_amount(amount: float, raw_desc: str, account_type: AccountType) -> float:
        if account_type == AccountType.CREDIT_CARD:
            desc_lower = raw_desc.lower()
            is_payment = any(
                w in desc_lower
                for w in [
                    "payment",
                    "thank you",
                    "autopay",
                    "credit",
                    "refund",
                    "cashback",
                    "reward",
                ]
            )
            if is_payment or amount < 0:
                return abs(amount)  # Balance credit (+)
            else:
                return -abs(amount)  # Purchase expense (-)
        return amount

    def parse(self, file_path: Path) -> Tuple[str, List[Transaction]]:
        transactions: List[Transaction] = []
        raw_pages: List[str] = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                raw_pages.append(text)

        full_raw_text = "\n--- PAGE BREAK ---\n".join(raw_pages)
        institution = self._detect_institution(full_raw_text, file_path.name)
        account_type = self._detect_account_type(full_raw_text)
        masked_account = self._detect_masked_account(full_raw_text)
        year = self._detect_year(full_raw_text)

        with pdfplumber.open(file_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                page_txs: List[Transaction] = []

                # Strategy 1: Tabular extraction
                tables = page.extract_tables()
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

                        norm_date = self._normalize_date(date_val, year)
                        norm_amount = self._normalize_amount(amount_val, raw_desc, account_type)

                        page_txs.append(
                            Transaction(
                                date=norm_date,
                                raw_description=raw_desc,
                                clean_merchant=raw_desc.strip(),
                                amount=norm_amount,
                                institution=institution,
                                account_type=account_type,
                                raw_metadata={
                                    "page": page_idx + 1,
                                    "raw_cells": cleaned_row,
                                    "account_number": masked_account,
                                },
                            )
                        )

                # Strategy 2: Line-stream fallback
                if not page_txs and text:
                    for line in text.splitlines():
                        line_str = line.strip()
                        if len(line_str) < 10:
                            continue

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

                        amt_matches = list(re.finditer(r"(-?\$?\s*[0-9,]+\.[0-9]{2})", line_str))
                        if not amt_matches:
                            continue

                        target_amt_match = amt_matches[0]
                        amt_raw = (
                            target_amt_match.group(1).replace("$", "").replace(",", "").strip()
                        )
                        try:
                            amount_val = float(amt_raw)
                        except ValueError:
                            continue

                        start_idx = date_match.end()
                        end_idx = target_amt_match.start()
                        raw_desc = (
                            line_str[start_idx:end_idx].strip()
                            if end_idx > start_idx
                            else line_str[:end_idx].strip()
                        )

                        if len(raw_desc) < 2:
                            continue

                        norm_date = self._normalize_date(date_match.group(0), year)
                        norm_amount = self._normalize_amount(amount_val, raw_desc, account_type)

                        page_txs.append(
                            Transaction(
                                date=norm_date,
                                raw_description=raw_desc,
                                clean_merchant=raw_desc.strip(),
                                amount=norm_amount,
                                institution=institution,
                                account_type=account_type,
                                raw_metadata={
                                    "page": page_idx + 1,
                                    "raw_line": line_str,
                                    "account_number": masked_account,
                                },
                            )
                        )

                transactions.extend(page_txs)

        return full_raw_text, transactions
