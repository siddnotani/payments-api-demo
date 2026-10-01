"""Payments demo API.

A deliberately small FastAPI service modelling a payments/transactions domain.
State is held in memory so the service runs with no external dependencies.
"""

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

import app.jobs  # noqa: F401  (registers in-app jobs)
from app import store
from app.models import Transaction, TransactionCreate, TransactionStatus
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
    return HealthResponse(status="ok", transactions=store.count_transactions())


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
    store.add_transaction(tx)
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
