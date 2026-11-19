import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

CREATE_OP = "#operations-transactions-create_transaction_transactions_post"
SUMMARY_OP = "#operations-analytics-analytics_summary_analytics_summary_get"

SAMPLE_TX = {
    "from_account": "ES9121000418450200051332",
    "to_account": "GB29NWBK60161331926819",
    "amount": "125.50",
    "currency": "EUR",
    "reference": "e2e",
}


def test_docs_lists_analytics_summary(page: Page):
    page.goto("/docs")

    expect(page.locator(".swagger-ui .info .title")).to_contain_text("Payments Demo API")
    expect(page.locator("#operations-tag-analytics")).to_be_visible()
    operation = page.locator(SUMMARY_OP)
    expect(operation).to_be_visible()
    expect(operation.locator(".opblock-summary-method")).to_have_text("GET")
    expect(operation.locator(".opblock-summary-path")).to_have_attribute(
        "data-path", "/analytics/summary"
    )


def test_create_transaction_then_summary_via_try_it_out(page: Page):
    page.goto("/docs")

    create = page.locator(CREATE_OP)
    create.locator(".opblock-summary").click()
    create.get_by_role("button", name="Try it out").click()
    create.locator("textarea.body-param__text").fill(json.dumps(SAMPLE_TX))
    create.get_by_role("button", name="Execute").click()
    expect(
        create.locator(".live-responses-table tr.response .response-col_status").first
    ).to_have_text("201")

    summary = page.locator(SUMMARY_OP)
    summary.locator(".opblock-summary").click()
    summary.get_by_role("button", name="Try it out").click()
    summary.get_by_role("button", name="Execute").click()
    expect(
        summary.locator(".live-responses-table tr.response .response-col_status").first
    ).to_have_text("200")
    response_body = summary.locator(
        ".live-responses-table tr.response .response-col_description pre"
    ).first
    expect(response_body).to_contain_text('"total_transactions": 1')


def test_openapi_schema_exposes_analytics_summary(page: Page):
    page.goto("/docs")

    schema = page.evaluate("async () => (await fetch('/openapi.json')).json()")

    assert "/analytics/summary" in schema["paths"]
    assert schema["paths"]["/analytics/summary"]["get"]["tags"] == ["analytics"]
