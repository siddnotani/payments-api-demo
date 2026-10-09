"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from datetime import UTC, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
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


class CurrencySummary(BaseModel):
    count: int
    total_amount: Decimal


class AnalyticsSummary(BaseModel):
    total_transactions: int
    total_amount_by_currency: dict[Currency, Decimal]
    count_by_currency: dict[Currency, int]
    count_by_status: dict[TransactionStatus, int]
    average_amount: Decimal | None
    largest_transaction: Transaction | None


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


IncidentScenario = Literal["fx_timeout", "ledger_drift", "duplicate_settlement"]

_INCIDENT_MESSAGES: dict[str, str] = {
    "fx_timeout": "FX rate provider timed out after 5000ms (provider=ecb, attempts=3)",
    "ledger_drift": "Ledger reconciliation drift: booked=1250.00 settled=1249.90 currency=EUR",
    "duplicate_settlement": "Settlement batch 2026-09-27-03 already exported; refusing to re-run",
}


_transactions: dict[str, Transaction] = {}

# Amounts are unbounded, so aggregate without the default 28-digit precision limit.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)


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
def analytics_summary() -> AnalyticsSummary:
    """Aggregate all stored transactions.

    `average_amount` is the mean of every amount regardless of currency, rounded
    half-even to 2 dp. Mixing currencies without FX conversion makes it imprecise;
    use `total_amount_by_currency` / `count_by_currency` for per-currency figures.
    """
    txs = list(_transactions.values())
    totals: dict[Currency, Decimal] = {}
    counts: dict[Currency, int] = {}
    statuses: dict[TransactionStatus, int] = {}
    for tx in txs:
        totals[tx.currency] = _EXACT.add(totals.get(tx.currency, Decimal(0)), tx.amount)
        counts[tx.currency] = counts.get(tx.currency, 0) + 1
        statuses[tx.status] = statuses.get(tx.status, 0) + 1

    average = None
    if txs:
        cents = round(sum(Fraction(tx.amount) for tx in txs) * 100 / len(txs))
        average = Decimal(cents).scaleb(-2, _EXACT)

    return AnalyticsSummary(
        total_transactions=len(txs),
        total_amount_by_currency=totals,
        count_by_currency=counts,
        count_by_status=statuses,
        average_amount=average,
        largest_transaction=max(txs, key=lambda t: t.amount, default=None),
    )
