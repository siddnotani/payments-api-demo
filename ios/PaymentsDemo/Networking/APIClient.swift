import Foundation

/// Thin async/await client for the Payments Demo FastAPI backend (`app/main.py`).
struct APIClient {
    let baseURLString: String
    var session: URLSession = .shared

    init(baseURLString: String, session: URLSession = .shared) {
        self.baseURLString = baseURLString
        self.session = session
    }

    // MARK: Transactions

    func listTransactions() async throws -> [Transaction] {
        try await send("GET", "transactions")
    }

    func transaction(id: String) async throws -> Transaction {
        try await send("GET", "transactions/\(id)")
    }

    func createTransaction(_ payload: TransactionCreate) async throws -> Transaction {
        try await send("POST", "transactions", body: payload)
    }

    // MARK: Ops

    func health() async throws -> HealthResponse {
        try await send("GET", "health")
    }

    func jobs() async throws -> [JobInfo] {
        try await send("GET", "ops/jobs")
    }

    func runJob(name: String, dryRun: Bool = true) async throws -> JobRunResponse {
        try await send(
            "POST", "ops/jobs/\(name)/run",
            query: [URLQueryItem(name: "dry_run", value: dryRun ? "true" : "false")]
        )
    }

    /// The backend always answers with a 500, so this throws `APIError.http` carrying the incident message.
    func triggerIncident(_ scenario: IncidentScenario) async throws {
        let _: [String: String] = try await send("POST", "ops/incidents/\(scenario.rawValue)")
    }

    // MARK: Plumbing

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            guard let date = parseISO8601(string) else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "Invalid ISO 8601 date \(string)"
                )
            }
            return date
        }
        return decoder
    }()

    static func parseISO8601(_ string: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: string) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: string)
    }

    func makeURL(_ path: String, query: [URLQueryItem] = []) throws -> URL {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            var components = URLComponents(string: trimmed),
            let scheme = components.scheme, ["http", "https"].contains(scheme),
            components.host != nil
        else {
            throw APIError.invalidBaseURL(baseURLString)
        }
        let basePath = components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path
        components.path = basePath + "/" + path
        components.queryItems = query.isEmpty ? nil : query
        guard let url = components.url else { throw APIError.invalidBaseURL(baseURLString) }
        return url
    }

    private func send<Response: Decodable>(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        body: (any Encodable)? = nil
    ) async throws -> Response {
        var request = URLRequest(url: try makeURL(path, query: query))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("error.no_http_response".localizedString)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(
                status: http.statusCode,
                message: APIErrorBody.message(from: data, status: http.statusCode)
            )
        }
        do {
            return try Self.decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }
}
