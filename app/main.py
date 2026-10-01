"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

import app.jobs  # noqa: F401  (registers in-app jobs)
from app import store
from app.models import (
    AccountBalance,
    BalanceEntry,
    Currency,
    DepositCreate,
    Direction,
    Statement,
    StatementEntry,
    Transaction,
    TransactionCreate,
    TransactionStatus,
)
from app.scheduler import registered_jobs, run_job

log = logging.getLogger("payments.api")

app = FastAPI(
    title="Payments Demo API",
    version="0.1.0",
    description="Minimal transactions API used for CI/CD and QA demos.",
)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    transactions: int
    accounts: int


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


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        transactions=store.count_transactions(),
        accounts=store.count_accounts(),
    )


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
    if store.EXTERNAL_ACCOUNT in (payload.from_account, payload.to_account):
        raise HTTPException(
            status_code=422,
            detail=f"{store.EXTERNAL_ACCOUNT} is a reserved account; use the deposits endpoint",
        )
    return _record(payload)


def _record(payload: TransactionCreate) -> Transaction:
    tx = Transaction(
        id=str(uuid4()),
        status=TransactionStatus.COMPLETED,
        created_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    try:
        store.add_transaction(tx)
    except store.InsufficientFundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return tx


@app.post(
    "/accounts/{account_id}/deposits",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
    tags=["accounts"],
)
def create_deposit(account_id: str, payload: DepositCreate) -> Transaction:
    """Credit an account from the EXTERNAL funding source."""
    if account_id == store.EXTERNAL_ACCOUNT:
        raise HTTPException(
            status_code=422,
            detail=f"{store.EXTERNAL_ACCOUNT} is a reserved account",
        )
    return _record(
        TransactionCreate(
            from_account=store.EXTERNAL_ACCOUNT,
            to_account=account_id,
            **payload.model_dump(),
        )
    )


@app.get("/accounts/{account_id}/balance", response_model=AccountBalance, tags=["accounts"])
def get_balance(account_id: str) -> AccountBalance:
    balances = store.get_balances(account_id)
    if balances is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )
    return AccountBalance(
        account=account_id,
        balances=[
            BalanceEntry(currency=currency, amount=amount)
            for currency, amount in sorted(balances.items())
        ],
    )


@app.get("/accounts/{account_id}/statement", response_model=Statement, tags=["accounts"])
def get_statement(
    account_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> Statement:
    """Entries ordered by created_at; date bounds are inclusive UTC calendar days.

    running_balance is the account's balance in the entry's currency after that entry,
    computed over the full history so it stays correct when filtering by date.
    """
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must be on or before to_date")
    transactions = store.list_account_transactions(account_id)
    if not transactions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )
    running: dict[Currency, Decimal] = {}
    entries: list[StatementEntry] = []
    for tx in transactions:
        is_debit = tx.from_account == account_id
        delta = -tx.amount if is_debit else tx.amount
        running[tx.currency] = running.get(tx.currency, Decimal("0")) + delta
        day = tx.created_at.astimezone(UTC).date()
        if (from_date and day < from_date) or (to_date and day > to_date):
            continue
        entries.append(
            StatementEntry(
                transaction_id=tx.id,
                direction=Direction.DEBIT if is_debit else Direction.CREDIT,
                counterparty=tx.to_account if is_debit else tx.from_account,
                amount=tx.amount,
                currency=tx.currency,
                reference=tx.reference,
                timestamp=tx.created_at,
                running_balance=running[tx.currency],
            )
        )
    return Statement(account=account_id, generated_at=datetime.now(UTC), entries=entries)


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
    return store.list_transactions()


@app.get("/transactions/{transaction_id}", response_model=Transaction, tags=["transactions"])
def get_transaction(transaction_id: str) -> Transaction:
    tx = store.get_transaction(transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found",
        )
    return tx
