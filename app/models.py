"""Domain models for the payments demo API."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Currency(StrEnum):
    EUR = "EUR"
    GBP = "GBP"
    USD = "USD"


class Direction(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


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


class DepositCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, examples=["500.00"])
    currency: Currency = Currency.EUR
    reference: str | None = Field(default=None, max_length=140)


class BalanceEntry(BaseModel):
    currency: Currency
    amount: Decimal


class AccountBalance(BaseModel):
    account: str
    balances: list[BalanceEntry]


class StatementEntry(BaseModel):
    transaction_id: str
    direction: Direction
    counterparty: str
    amount: Decimal
    currency: Currency
    reference: str | None
    timestamp: datetime
    running_balance: Decimal


class Statement(BaseModel):
    account: str
    generated_at: datetime
    entries: list[StatementEntry]
