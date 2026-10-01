import XCTest
@testable import PaymentsDemo

final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (Int, Data))?
    static var lastRequest: URLRequest?
    static var lastBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lastRequest = request
        Self.lastBody = request.httpBody ?? request.httpBodyStream.map(Self.read)
        let (status, data) = Self.handler?(request) ?? (500, Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func read(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            data.append(buffer, count: count)
        }
        return data
    }
}

final class APIClientTests: XCTestCase {
    private var client: APIClient!

    override func setUp() {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        client = APIClient(baseURLString: "http://localhost:8000", session: URLSession(configuration: config))
    }

    override func tearDown() {
        StubURLProtocol.handler = nil
        StubURLProtocol.lastRequest = nil
        StubURLProtocol.lastBody = nil
    }

    private let txJSON = #"{"from_account":"A1","to_account":"B2","amount":"10.5","currency":"GBP","reference":null,"id":"abc","status":"COMPLETED","created_at":"2026-10-01T18:33:28.027506Z"}"#

    func testListTransactions() async throws {
        StubURLProtocol.handler = { _ in (200, Data("[\(self.txJSON)]".utf8)) }

        let list = try await client.listTransactions()

        XCTAssertEqual(list.map(\.id), ["abc"])
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "GET")
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.absoluteString, "http://localhost:8000/transactions")
    }

    func testEmptyTransactionList() async throws {
        StubURLProtocol.handler = { _ in (200, Data("[]".utf8)) }

        let list = try await client.listTransactions()

        XCTAssertTrue(list.isEmpty)
    }

    func testTransactionDetailNotFound() async {
        StubURLProtocol.handler = { _ in (404, Data(#"{"detail":"Transaction nope not found"}"#.utf8)) }

        do {
            _ = try await client.transaction(id: "nope")
            XCTFail("expected 404")
        } catch {
            XCTAssertEqual(error as? APIError, .http(status: 404, message: "Transaction nope not found"))
            XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/transactions/nope")
        }
    }

    func testCreateTransactionPostsJSONBody() async throws {
        StubURLProtocol.handler = { _ in (201, Data(self.txJSON.utf8)) }
        let payload = TransactionCreate(
            fromAccount: "A1", toAccount: "B2", amount: Decimal(string: "10.5")!, currency: .GBP, reference: "Ref"
        )

        let created = try await client.createTransaction(payload)

        XCTAssertEqual(created.status, .COMPLETED)
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(StubURLProtocol.lastRequest?.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let body = try XCTUnwrap(StubURLProtocol.lastBody)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        XCTAssertEqual(object["amount"], "10.5")
        XCTAssertEqual(object["reference"], "Ref")
    }

    func testCreateTransactionSurfaces422Detail() async {
        StubURLProtocol.handler = { _ in (422, Data(#"{"detail":"from_account and to_account must differ"}"#.utf8)) }
        let payload = TransactionCreate(fromAccount: "A1", toAccount: "A1", amount: 1, currency: .EUR, reference: nil)

        do {
            _ = try await client.createTransaction(payload)
            XCTFail("expected 422")
        } catch {
            XCTAssertEqual(error as? APIError, .http(status: 422, message: "from_account and to_account must differ"))
        }
    }

    func testRunJobSendsDryRunQuery() async throws {
        StubURLProtocol.handler = { _ in (200, Data(#"{"job":"heartbeat","processed":0,"notes":[]}"#.utf8)) }

        let result = try await client.runJob(name: "heartbeat", dryRun: false)

        XCTAssertEqual(result.job, "heartbeat")
        XCTAssertEqual(
            StubURLProtocol.lastRequest?.url?.absoluteString, "http://localhost:8000/ops/jobs/heartbeat/run?dry_run=false"
        )
    }

    func testTriggerIncidentThrowsServerError() async {
        StubURLProtocol.handler = { _ in (500, Data(#"{"scenario":"ledger_drift","error":"Ledger drift"}"#.utf8)) }

        do {
            try await client.triggerIncident(.ledgerDrift)
            XCTFail("expected 500")
        } catch {
            XCTAssertEqual(error as? APIError, .http(status: 500, message: "Ledger drift"))
            XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/ops/incidents/ledger_drift")
        }
    }

    func testHealthAndJobs() async throws {
        StubURLProtocol.handler = { request in
            request.url?.path == "/health"
                ? (200, Data(#"{"status":"ok","transactions":2}"#.utf8))
                : (200, Data(#"[{"name":"heartbeat","schedule":"*/5 * * * *","description":""}]"#.utf8))
        }

        let health = try await client.health()
        let jobs = try await client.jobs()

        XCTAssertEqual(health.transactions, 2)
        XCTAssertEqual(jobs.first?.name, "heartbeat")
    }

    func testBaseURLHandling() throws {
        XCTAssertEqual(
            try APIClient(baseURLString: "http://10.0.0.5:8000/api/").makeURL("health").absoluteString,
            "http://10.0.0.5:8000/api/health"
        )
        XCTAssertThrowsError(try APIClient(baseURLString: "not a url").makeURL("health")) { error in
            XCTAssertEqual(error as? APIError, .invalidBaseURL("not a url"))
        }
    }
}
