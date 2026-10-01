"""In-memory persistence for the payments demo API."""

from app.models import Transaction

_transactions: dict[str, Transaction] = {}


def reset_store() -> None:
    """Clear all stored transactions (used by tests)."""
    _transactions.clear()


def add_transaction(tx: Transaction) -> None:
    _transactions[tx.id] = tx


def get_transaction(transaction_id: str) -> Transaction | None:
    return _transactions.get(transaction_id)


def list_transactions() -> list[Transaction]:
    return sorted(_transactions.values(), key=lambda t: t.created_at)


def count_transactions() -> int:
    return len(_transactions)
