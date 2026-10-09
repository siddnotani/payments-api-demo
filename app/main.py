"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from datetime import UTC, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal
from enum import StrEnum
from fractions import Fraction
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


class AnalyticsSummary(BaseModel):
    total_transactions: int
    total_amount_by_currency: dict[Currency, Decimal]
    count_by_status: dict[TransactionStatus, int]
    count_by_currency: dict[Currency, int]
    average_amount: Decimal | None
    largest_transaction: Transaction | None
    first_transaction_at: datetime | None
    last_transaction_at: datetime | None


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


def reset_store() -> None:
    """Clear all stored transactions (used by tests)."""
    _transactions.clear()


# Unbounded precision so sums of arbitrarily large accepted amounts stay exact.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _average_to_cents(total: Decimal, count: int) -> Decimal:
    """Exact mean rounded half-even to 2 dp (Fraction avoids Decimal precision limits)."""
    cents = round(Fraction(total) * 100 / count)
    return Decimal(cents).scaleb(-2, _EXACT)


def compute_analytics(
    transactions: list[Transaction],
    currency: Currency | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    account: str | None = None,
) -> AnalyticsSummary:
    """Aggregate transactions with exact Decimal math; `since`/`until` are inclusive."""
    since, until = _as_utc(since), _as_utc(until)
    selected = sorted(
        (
            tx
            for tx in transactions
            if (currency is None or tx.currency == currency)
            and (since is None or tx.created_at >= since)
            and (until is None or tx.created_at <= until)
            and (account is None or account in (tx.from_account, tx.to_account))
        ),
        key=lambda t: t.created_at,
    )

    total_by_currency = {c: Decimal(0) for c in Currency}
    count_by_currency = {c: 0 for c in Currency}
    count_by_status = {s: 0 for s in TransactionStatus}
    grand_total = Decimal(0)
    for tx in selected:
        total_by_currency[tx.currency] = _EXACT.add(total_by_currency[tx.currency], tx.amount)
        grand_total = _EXACT.add(grand_total, tx.amount)
        count_by_currency[tx.currency] += 1
        count_by_status[tx.status] += 1

    return AnalyticsSummary(
        total_transactions=len(selected),
        total_amount_by_currency=total_by_currency,
        count_by_status=count_by_status,
        count_by_currency=count_by_currency,
        average_amount=_average_to_cents(grand_total, len(selected)) if selected else None,
        # max() keeps the first maximum, so ties resolve to the earliest transaction.
        largest_transaction=max(selected, key=lambda t: t.amount, default=None),
        first_transaction_at=selected[0].created_at if selected else None,
        last_transaction_at=selected[-1].created_at if selected else None,
    )


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


@app.get("/analytics/summary", response_model=AnalyticsSummary, tags=["analytics"])
def analytics_summary(
    currency: Currency | None = None,
    since: Annotated[datetime | None, Query(description="Inclusive ISO 8601 lower bound")] = None,
    until: Annotated[datetime | None, Query(description="Inclusive ISO 8601 upper bound")] = None,
    account: Annotated[str | None, Query(min_length=1, description="from or to account")] = None,
) -> AnalyticsSummary:
    """Aggregate the transaction store; naive datetimes are treated as UTC."""
    if since is not None and until is not None and _as_utc(since) > _as_utc(until):
        raise HTTPException(status_code=422, detail="since must not be after until")
    return compute_analytics(list(_transactions.values()), currency, since, until, account)


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
