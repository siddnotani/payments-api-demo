"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from datetime import UTC, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal
from enum import StrEnum
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


class HealthResponse(BaseModel):
    status: Literal["ok"]
    transactions: int


class CurrencyBreakdown(BaseModel):
    currency: Currency
    count: int
    total_amount: Decimal
    min_amount: Decimal
    max_amount: Decimal
    avg_amount: Decimal


class AnalyticsSummary(BaseModel):
    count: int
    breakdowns: list[CurrencyBreakdown]


class AccountAnalytics(BaseModel):
    account: str
    sent_count: int
    received_count: int
    sent_total: dict[Currency, Decimal]
    received_total: dict[Currency, Decimal]


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


# Amounts are unbounded, so aggregate in a context that never rounds or overflows.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)


def _average(total: Decimal, count: int) -> Decimal:
    """Mean rounded half-up to 2 decimal places, using exact integer division."""
    quotient, remainder = _EXACT.divmod(_EXACT.scaleb(total, 2), count)
    if _EXACT.multiply(remainder, 2) >= count:
        quotient = _EXACT.add(quotient, 1)
    return _EXACT.scaleb(quotient, -2)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


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
    since: datetime | None = None,
    until: datetime | None = None,
) -> AnalyticsSummary:
    """Per-currency aggregates; `since`/`until` bound created_at inclusively (naive = UTC)."""
    since, until = _as_utc(since), _as_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=422, detail="since must not be after until")

    groups: dict[Currency, list[Decimal]] = {}
    for tx in _transactions.values():
        if currency is not None and tx.currency != currency:
            continue
        if since is not None and tx.created_at < since:
            continue
        if until is not None and tx.created_at > until:
            continue
        groups.setdefault(tx.currency, []).append(tx.amount)

    breakdowns = []
    for cur in Currency:
        amounts = groups.get(cur)
        if not amounts:
            continue
        total = Decimal(0)
        for amount in amounts:
            total = _EXACT.add(total, amount)
        breakdowns.append(
            CurrencyBreakdown(
                currency=cur,
                count=len(amounts),
                total_amount=total,
                min_amount=min(amounts),
                max_amount=max(amounts),
                avg_amount=_average(total, len(amounts)),
            )
        )
    return AnalyticsSummary(count=sum(b.count for b in breakdowns), breakdowns=breakdowns)


@app.get("/analytics/by-account/{account}", response_model=AccountAnalytics, tags=["analytics"])
def analytics_by_account(account: str) -> AccountAnalytics:
    sent_count = received_count = 0
    sent_total: dict[Currency, Decimal] = {}
    received_total: dict[Currency, Decimal] = {}
    for tx in _transactions.values():
        if tx.from_account == account:
            sent_count += 1
            sent_total[tx.currency] = _EXACT.add(sent_total.get(tx.currency, 0), tx.amount)
        if tx.to_account == account:
            received_count += 1
            received_total[tx.currency] = _EXACT.add(received_total.get(tx.currency, 0), tx.amount)
    if sent_count == 0 and received_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transactions for account {account}",
        )
    return AccountAnalytics(
        account=account,
        sent_count=sent_count,
        received_count=received_count,
        sent_total=sent_total,
        received_total=received_total,
    )


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
