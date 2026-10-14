import csv
from pathlib import Path
from typing import Tuple, List
from src.models.schemas import Transaction, AccountType
from src.parsers.base import BaseStatementParser


class CSVStatementParser(BaseStatementParser):
    """Tier 1 non-destructive parser for tabular CSV exports with automated credit card sign normalization."""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv"

    @staticmethod
    def _detect_institution(filename: str) -> str:
        fn = filename.lower()
        if "discover" in fn:
            return "Discover"
        elif "chase" in fn:
            return "Chase"
        elif "apple" in fn:
            return "Apple Card"
        elif "citi" in fn:
            return "Citi"
        elif "rocket" in fn:
            return "RocketMoney"
        return "Generic CSV"

    @staticmethod
    def _detect_account_type(filename: str, field_map: dict) -> AccountType:
        fn = filename.lower()
        if any(w in fn for w in ["card", "discover", "credit", "amex"]):
            return AccountType.CREDIT_CARD
        if any(k in field_map for k in ["trans. date", "post date"]):
            return AccountType.CREDIT_CARD
        if "rocket" in fn:
            return AccountType.AGGREGATOR
        return AccountType.CHECKING

    def parse(self, file_path: Path) -> Tuple[str, List[Transaction]]:
        transactions: List[Transaction] = []
        raw_csv_text = file_path.read_text(encoding="utf-8-sig")
        lines = raw_csv_text.splitlines()
        if not lines:
            return raw_csv_text, []

        reader = csv.DictReader(lines)
        if not reader.fieldnames:
            return raw_csv_text, []

        field_map = {name.lower().strip(): name for name in reader.fieldnames}
        institution = self._detect_institution(file_path.name)
        account_type = self._detect_account_type(file_path.name, field_map)

        # Identify core columns
        date_col = next((field_map[k] for k in field_map if "date" in k or "time" in k), None)
        desc_col = next(
            (
                field_map[k]
                for k in field_map
                if any(w in k for w in ["desc", "merchant", "name", "payee"])
            ),
            None,
        )
        amt_col = next((field_map[k] for k in field_map if "amount" in k or "amt" in k), None)
        debit_col = next((field_map[k] for k in field_map if "debit" in k or "charge" in k), None)
        credit_col = next(
            (field_map[k] for k in field_map if "credit" in k or "deposit" in k), None
        )

        if not date_col or not desc_col:
            return raw_csv_text, []

        for row in reader:
            raw_date = row.get(date_col, "").strip()
            raw_desc = row.get(desc_col, "").strip()
            if not raw_date or not raw_desc:
                continue

            # Calculate signed amount
            amount = 0.0
            if amt_col and row.get(amt_col):
                cleaned_amt = row[amt_col].replace("$", "").replace(",", "").strip()
                amount = float(cleaned_amt) if cleaned_amt else 0.0

                # Credit card sign normalization for single-amount columns
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
                        amount = abs(amount)  # Card balance credit (+)
                    else:
                        amount = -abs(amount)  # Card purchase expense (-)

            elif debit_col or credit_col:
                debit_val = (
                    float(row[debit_col].replace("$", "").replace(",", "").strip() or 0.0)
                    if debit_col and row.get(debit_col)
                    else 0.0
                )
                credit_val = (
                    float(row[credit_col].replace("$", "").replace(",", "").strip() or 0.0)
                    if credit_col and row.get(credit_col)
                    else 0.0
                )
                amount = credit_val - debit_val

            extra_metadata = {
                k: v
                for k, v in row.items()
                if k not in [date_col, desc_col, amt_col, debit_col, credit_col] and v
            }

            transactions.append(
                Transaction(
                    date=raw_date,
                    raw_description=raw_desc,
                    clean_merchant=raw_desc.strip(),
                    amount=amount,
                    institution=institution,
                    account_type=account_type,
                    raw_metadata=extra_metadata,
                )
            )

        return raw_csv_text, transactions
