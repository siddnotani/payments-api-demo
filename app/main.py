"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_UP, Context, Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

import app.jobs  # noqa: F401  (registers in-app jobs)
from app.scheduler import registered_jobs, run_job

log = logging.getLogger("payments.api")

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


class JobInfo(BaseModel):
    name: str
    schedule: str
    description: str


class JobRunResponse(BaseModel):
    job: str
    processed: int
    notes: list[str]


class CurrencySummary(BaseModel):
    currency: Currency = Field(..., examples=["EUR"])
    count: int = Field(..., ge=0, examples=[3])
    total_amount: Decimal = Field(..., examples=["376.50"])
    average_amount: Decimal = Field(..., examples=["125.50"])


class AnalyticsSummary(BaseModel):
    total_transactions: int = Field(..., ge=0, examples=[5])
    per_currency: list[CurrencySummary]
    largest_transaction: Transaction | None


IncidentScenario = Literal["fx_timeout", "ledger_drift", "duplicate_settlement"]

_INCIDENT_MESSAGES: dict[str, str] = {
    "fx_timeout": "FX rate provider timed out after 5000ms (provider=ecb, attempts=3)",
    "ledger_drift": "Ledger reconciliation drift: booked=1250.00 settled=1249.90 currency=EUR",
    "duplicate_settlement": "Settlement batch 2026-09-27-03 already exported; refusing to re-run",
}


_transactions: dict[str, Transaction] = {}

# Amounts are unbounded, so aggregate exactly rather than in the default 28-digit context.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
_CENTS = Decimal("0.01")


def _round_cents(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP, context=_EXACT)


def _average_cents(total: Decimal, count: int) -> Decimal:
    """total / count rounded half up to 2 places, using exact integer division."""
    quotient, remainder = _EXACT.divmod(_EXACT.scaleb(total, 2), Decimal(count))
    if _EXACT.multiply(remainder, 2) >= count:
        quotient = _EXACT.add(quotient, 1)
    return _EXACT.scaleb(quotient, -2)


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
        status=TransactionStatus.COMPLETED,
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    _transactions[tx.id] = tx
    return tx


@app.get("/ops/jobs", response_model=list[JobInfo], tags=["ops"])
def list_jobs() -> list[JobInfo]:
    """Jobs migrated onto the in-app scheduler (legacy scripts in jobs/ are not listed)."""
    return [
        JobInfo(name=j.name, schedule=j.schedule, description=j.description)
        for j in registered_jobs()
    ]


@app.post("/ops/jobs/{name}/run", response_model=JobRunResponse, tags=["ops"])
def trigger_job(name: str, dry_run: bool = True) -> JobRunResponse:
    if name not in {j.name for j in registered_jobs()}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {name} not found")
    result = run_job(name, dry_run=dry_run)
    return JobRunResponse(job=name, processed=result.processed, notes=result.notes)


@app.post(
    "/ops/incidents/{scenario}",
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    tags=["ops"],
)
def simulate_incident(scenario: IncidentScenario) -> dict[str, str]:
    """Emit a structured error and return a 500 so an alerting pipeline can page on it."""
    message = _INCIDENT_MESSAGES[scenario]
    log.error("incident.simulated", extra={"scenario": scenario, "detail": message})
    return {"scenario": scenario, "error": message}


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


@app.get("/analytics/summary", response_model=AnalyticsSummary, tags=["analytics"])
def analytics_summary(
    account: Annotated[
        str | None,
        Query(min_length=1, description="Only include transactions sent or received by account"),
    ] = None,
) -> AnalyticsSummary:
    txs = sorted(_transactions.values(), key=lambda t: t.created_at)
    if account is not None:
        txs = [t for t in txs if account in (t.from_account, t.to_account)]

    by_currency: dict[Currency, list[Decimal]] = defaultdict(list)
    for tx in txs:
        by_currency[tx.currency].append(tx.amount)

    per_currency = []
    for currency in sorted(by_currency):
        amounts = by_currency[currency]
        total = Decimal(0)
        for amount in amounts:
            total = _EXACT.add(total, amount)
        per_currency.append(
            CurrencySummary(
                currency=currency,
                count=len(amounts),
                total_amount=_round_cents(total),
                average_amount=_average_cents(total, len(amounts)),
            )
        )

    return AnalyticsSummary(
        total_transactions=len(txs),
        per_currency=per_currency,
        largest_transaction=max(txs, key=lambda t: t.amount, default=None),
    )
