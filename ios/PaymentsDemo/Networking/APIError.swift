import Foundation

enum APIError: LocalizedError, Equatable {
    case invalidBaseURL(String)
    case transport(String)
    case http(status: Int, message: String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL(let url):
            return String(format: "error.invalid_base_url_format".localizedString, url)
        case .transport(let message):
            return String(format: "error.transport_format".localizedString, message)
        case .http(let status, let message):
            return String(format: "error.http_format".localizedString, status, message)
        case .decoding(let message):
            return String(format: "error.decoding_format".localizedString, message)
        }
    }

    var statusCode: Int? {
        if case .http(let status, _) = self { return status }
        return nil
    }
}

/// Error payloads returned by the API:
/// - `HTTPException`: `{"detail": "message"}`
/// - request validation (422): `{"detail": [{"loc": [...], "msg": "..."}]}`
/// - simulated incidents (500): `{"scenario": "...", "error": "message"}`
struct APIErrorBody: Decodable {
    struct ValidationIssue: Decodable {
        let loc: [LocationPart]
        let msg: String

        var summary: String {
            let field = loc.map(\.description).filter { $0 != "body" }.joined(separator: ".")
            return field.isEmpty ? msg : "\(field): \(msg)"
        }
    }

    enum LocationPart: Decodable, CustomStringConvertible {
        case key(String)
        case index(Int)

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let index = try? container.decode(Int.self) {
                self = .index(index)
            } else {
                self = .key(try container.decode(String.self))
            }
        }

        var description: String {
            switch self {
            case .key(let key): return key
            case .index(let index): return String(index)
            }
        }
    }

    let message: String?

    enum CodingKeys: String, CodingKey {
        case detail, error
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let detail = try? container.decode(String.self, forKey: .detail) {
            message = detail
        } else if let issues = try? container.decode([ValidationIssue].self, forKey: .detail) {
            message = issues.map(\.summary).joined(separator: "\n")
        } else {
            message = try container.decodeIfPresent(String.self, forKey: .error)
        }
    }

    static func message(from data: Data, status: Int) -> String {
        if let body = try? JSONDecoder().decode(APIErrorBody.self, from: data), let message = body.message {
            return message
        }
        if let text = String(data: data, encoding: .utf8), !text.isEmpty {
            return text
        }
        return HTTPURLResponse.localizedString(forStatusCode: status)
    }
}
