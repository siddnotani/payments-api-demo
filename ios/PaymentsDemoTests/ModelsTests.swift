import XCTest
@testable import PaymentsDemo

final class ModelsTests: XCTestCase {
    func testDecodesTransactionFromAPIPayload() throws {
        let json = """
        {"from_account":"ES9121000418450200051332","to_account":"GB29NWBK60161331926819",
         "amount":"125.50","currency":"EUR","reference":"Invoice 42",
         "id":"4248857c-cab3-4369-bccb-58bdf3177b57","status":"COMPLETED",
         "created_at":"2026-10-01T18:33:28.027506Z"}
        """
        let tx = try APIClient.decoder.decode(Transaction.self, from: Data(json.utf8))

        XCTAssertEqual(tx.id, "4248857c-cab3-4369-bccb-58bdf3177b57")
        XCTAssertEqual(tx.fromAccount, "ES9121000418450200051332")
        XCTAssertEqual(tx.toAccount, "GB29NWBK60161331926819")
        XCTAssertEqual(tx.amount, Decimal(string: "125.50"))
        XCTAssertEqual(tx.currency, .EUR)
        XCTAssertEqual(tx.reference, "Invoice 42")
        XCTAssertEqual(tx.status, .COMPLETED)
        XCTAssertEqual(tx.createdAt.timeIntervalSince1970, 1_790_879_608.027, accuracy: 0.001)
    }

    func testDecodesNullReferenceAndDateWithoutFraction() throws {
        let json = """
        {"from_account":"A","to_account":"B","amount":10,"currency":"USD","reference":null,
         "id":"x","status":"PENDING","created_at":"2026-10-01T18:33:28Z"}
        """
        let tx = try APIClient.decoder.decode(Transaction.self, from: Data(json.utf8))

        XCTAssertNil(tx.reference)
        XCTAssertEqual(tx.amount, 10)
        XCTAssertEqual(tx.status, .PENDING)
    }

    func testEncodesTransactionCreateWithSnakeCaseAndDecimalString() throws {
        let payload = TransactionCreate(
            fromAccount: "A1", toAccount: "B2", amount: Decimal(string: "125.5")!, currency: .GBP, reference: nil
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(payload)) as? [String: String]
        )

        XCTAssertEqual(object, ["from_account": "A1", "to_account": "B2", "amount": "125.5", "currency": "GBP"])
    }

    func testDecodesHealthJobsAndJobRun() throws {
        let health = try APIClient.decoder.decode(
            HealthResponse.self, from: Data(#"{"status":"ok","transactions":3}"#.utf8)
        )
        let jobs = try APIClient.decoder.decode(
            [JobInfo].self,
            from: Data(#"[{"name":"heartbeat","schedule":"*/5 * * * *","description":"alive"}]"#.utf8)
        )
        let run = try APIClient.decoder.decode(
            JobRunResponse.self, from: Data(#"{"job":"heartbeat","processed":0,"notes":["alive"]}"#.utf8)
        )

        XCTAssertEqual(health, HealthResponse(status: "ok", transactions: 3))
        XCTAssertEqual(jobs.map(\.name), ["heartbeat"])
        XCTAssertEqual(run, JobRunResponse(job: "heartbeat", processed: 0, notes: ["alive"]))
    }

    func testErrorBodyMessages() {
        let validation = #"{"detail":[{"type":"greater_than","loc":["body","amount"],"msg":"Input should be greater than 0","input":"-1","ctx":{"gt":0}}]}"#
        let http = #"{"detail":"from_account and to_account must differ"}"#
        let incident = #"{"scenario":"fx_timeout","error":"FX rate provider timed out"}"#

        XCTAssertEqual(APIErrorBody.message(from: Data(validation.utf8), status: 422), "amount: Input should be greater than 0")
        XCTAssertEqual(APIErrorBody.message(from: Data(http.utf8), status: 422), "from_account and to_account must differ")
        XCTAssertEqual(APIErrorBody.message(from: Data(incident.utf8), status: 500), "FX rate provider timed out")
        XCTAssertEqual(APIErrorBody.message(from: Data("oops".utf8), status: 500), "oops")
    }

    func testAccountTruncationAndDecimalInput() {
        XCTAssertEqual(AccountFormatter.truncated("ES9121000418450200051332"), "ES91…1332")
        XCTAssertEqual(AccountFormatter.truncated("ACC-1"), "ACC-1")
        XCTAssertEqual(DecimalInput.parse("10,5", locale: Locale(identifier: "de_DE")), Decimal(string: "10.5"))
        XCTAssertEqual(DecimalInput.parse("125.50", locale: Locale(identifier: "en_US")), Decimal(string: "125.50"))
        XCTAssertNil(DecimalInput.parse("abc"))
        XCTAssertNil(DecimalInput.parse(" "))
    }
}
