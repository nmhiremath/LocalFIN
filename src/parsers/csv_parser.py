import csv
from pathlib import Path
from typing import Tuple, List
from src.models.schemas import Transaction, AccountType
from src.parsers.base import BaseStatementParser


class CSVStatementParser(BaseStatementParser):
    """Tier 1 non-destructive parser for tabular CSV exports."""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv"

    def parse(self, file_path: Path) -> Tuple[str, List[Transaction]]:
        transactions: List[Transaction] = []
        institution = "RocketMoney" if "rocket" in file_path.name.lower() else "Generic CSV"

        raw_csv_text = file_path.read_text(encoding="utf-8-sig")
        lines = raw_csv_text.splitlines()
        if not lines:
            return raw_csv_text, []

        reader = csv.DictReader(lines)
        if not reader.fieldnames:
            return raw_csv_text, []

        field_map = {name.lower().strip(): name for name in reader.fieldnames}

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

            # Preserve all extra columns into raw_metadata for downstream enrichment
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
                    account_type=AccountType.AGGREGATOR
                    if "rocket" in institution.lower()
                    else AccountType.CHECKING,
                    raw_metadata=extra_metadata,
                )
            )

        return raw_csv_text, transactions
