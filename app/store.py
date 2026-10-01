"""In-memory persistence for the payments demo API."""

from decimal import Decimal

from app.models import Currency, Transaction

EXTERNAL_ACCOUNT = "EXTERNAL"

_transactions: dict[str, Transaction] = {}
_balances: dict[str, dict[Currency, Decimal]] = {}


class InsufficientFundsError(Exception):
    def __init__(self, account: str, currency: Currency) -> None:
        super().__init__(f"Insufficient funds in {account} for {currency}")
        self.account = account
        self.currency = currency


def reset_store() -> None:
    """Clear all stored transactions and balances (used by tests)."""
    _transactions.clear()
    _balances.clear()


def add_transaction(tx: Transaction) -> None:
    """Store a transaction and apply it to balances.

    Raises InsufficientFundsError without mutating state if the debit would make the
    sender's balance negative. Deposits (from EXTERNAL_ACCOUNT) are not debited.
    """
    if tx.from_account != EXTERNAL_ACCOUNT:
        available = _balances.get(tx.from_account, {}).get(tx.currency, Decimal("0"))
        if available < tx.amount:
            raise InsufficientFundsError(tx.from_account, tx.currency)
        _adjust_balance(tx.from_account, tx.currency, -tx.amount)
    _adjust_balance(tx.to_account, tx.currency, tx.amount)
    _transactions[tx.id] = tx


def _adjust_balance(account: str, currency: Currency, delta: Decimal) -> None:
    balances = _balances.setdefault(account, {})
    balances[currency] = balances.get(currency, Decimal("0")) + delta


def get_transaction(transaction_id: str) -> Transaction | None:
    return _transactions.get(transaction_id)


def list_transactions() -> list[Transaction]:
    return sorted(_transactions.values(), key=lambda t: t.created_at)


def list_account_transactions(account: str) -> list[Transaction]:
    return [t for t in list_transactions() if account in (t.from_account, t.to_account)]


def count_transactions() -> int:
    return len(_transactions)


def get_balances(account: str) -> dict[Currency, Decimal] | None:
    balances = _balances.get(account)
    return dict(balances) if balances is not None else None


def count_accounts() -> int:
    return len(_balances)
