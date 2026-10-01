import Foundation

enum Currency: String, Codable, CaseIterable, Identifiable {
    case EUR, GBP, USD

    var id: String { rawValue }
}

enum TransactionStatus: String, Codable {
    case PENDING, COMPLETED
}

/// Request body for `POST /transactions`. `amount` is sent as a decimal string.
struct TransactionCreate: Encodable, Equatable {
    var fromAccount: String
    var toAccount: String
    var amount: Decimal
    var currency: Currency
    var reference: String?

    enum CodingKeys: String, CodingKey {
        case fromAccount = "from_account"
        case toAccount = "to_account"
        case amount, currency, reference
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(fromAccount, forKey: .fromAccount)
        try container.encode(toAccount, forKey: .toAccount)
        try container.encode(amount.description, forKey: .amount)
        try container.encode(currency, forKey: .currency)
        try container.encodeIfPresent(reference, forKey: .reference)
    }
}

struct Transaction: Decodable, Identifiable, Hashable {
    let id: String
    let fromAccount: String
    let toAccount: String
    let amount: Decimal
    let currency: Currency
    let reference: String?
    let status: TransactionStatus
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case fromAccount = "from_account"
        case toAccount = "to_account"
        case amount, currency, reference, status
        case createdAt = "created_at"
    }

    init(
        id: String,
        fromAccount: String,
        toAccount: String,
        amount: Decimal,
        currency: Currency,
        reference: String?,
        status: TransactionStatus,
        createdAt: Date
    ) {
        self.id = id
        self.fromAccount = fromAccount
        self.toAccount = toAccount
        self.amount = amount
        self.currency = currency
        self.reference = reference
        self.status = status
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        fromAccount = try container.decode(String.self, forKey: .fromAccount)
        toAccount = try container.decode(String.self, forKey: .toAccount)
        amount = try container.decodeDecimalString(forKey: .amount)
        currency = try container.decode(Currency.self, forKey: .currency)
        reference = try container.decodeIfPresent(String.self, forKey: .reference)
        status = try container.decode(TransactionStatus.self, forKey: .status)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
    }
}

struct HealthResponse: Decodable, Equatable {
    let status: String
    let transactions: Int
}

struct JobInfo: Decodable, Identifiable, Hashable {
    let name: String
    let schedule: String
    let description: String

    var id: String { name }
}

struct JobRunResponse: Decodable, Equatable {
    let job: String
    let processed: Int
    let notes: [String]
}

enum IncidentScenario: String, CaseIterable, Identifiable {
    case fxTimeout = "fx_timeout"
    case ledgerDrift = "ledger_drift"
    case duplicateSettlement = "duplicate_settlement"

    var id: String { rawValue }
}

private extension KeyedDecodingContainer {
    /// Pydantic serialises `Decimal` as a JSON string; accept a number as well.
    func decodeDecimalString(forKey key: Key) throws -> Decimal {
        if let string = try? decode(String.self, forKey: key) {
            guard let value = Decimal(string: string, locale: Locale(identifier: "en_US_POSIX")) else {
                throw DecodingError.dataCorruptedError(
                    forKey: key, in: self, debugDescription: "Invalid decimal string \(string)"
                )
            }
            return value
        }
        return try decode(Decimal.self, forKey: key)
    }
}
