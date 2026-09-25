"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

app = FastAPI(
    title="Payments Demo API",
    version="0.1.0",
    description="Minimal transactions API used for CI/CD and QA demos.",
)


class Currency(StrEnum):
    EUR = "EUR"
    GBP = "GBP"
    USD = "USD"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class TransactionCreate(BaseModel):
    from_account: str = Field(..., min_length=1, examples=["ES9121000418450200051332"])
    to_account: str = Field(..., min_length=1, examples=["GB29NWBK60161331926819"])
    amount: Decimal = Field(..., gt=0, examples=["125.50"])
    currency: Currency = Currency.EUR
    reference: str | None = Field(default=None, max_length=140)


class Transaction(TransactionCreate):
    id: str
    status: TransactionStatus
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"]
    transactions: int


_transactions: dict[str, Transaction] = {}


def reset_store() -> None:
    """Clear all stored transactions (used by tests)."""
    _transactions.clear()


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", transactions=len(_transactions))


@app.post(
    "/transactions",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
    tags=["transactions"],
)
def create_transaction(payload: TransactionCreate) -> Transaction:
    if payload.from_account == payload.to_account:
        raise HTTPException(
            status_code=422,
            detail="from_account and to_account must differ",
        )
    tx = Transaction(
        id=str(uuid4()),
        status=TransactionStatus.PENDING,
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    _transactions[tx.id] = tx
    return tx


@app.get("/transactions", response_model=list[Transaction], tags=["transactions"])
def list_transactions() -> list[Transaction]:
    return sorted(_transactions.values(), key=lambda t: t.created_at)


@app.get("/transactions/{transaction_id}", response_model=Transaction, tags=["transactions"])
def get_transaction(transaction_id: str) -> Transaction:
    tx = _transactions.get(transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found",
        )
    return tx


@app.post(
    "/transactions/{transaction_id}/confirm",
    response_model=Transaction,
    tags=["transactions"],
)
def confirm_transaction(transaction_id: str) -> Transaction:
    tx = _transactions.get(transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found",
        )
    if tx.status != TransactionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transaction {transaction_id} is {tx.status}; "
                "only PENDING transactions can be confirmed"
            ),
        )
    confirmed = tx.model_copy(update={"status": TransactionStatus.COMPLETED})
    _transactions[transaction_id] = confirmed
    return confirmed
