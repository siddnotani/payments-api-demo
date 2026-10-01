import Foundation

extension Transaction {
    var formattedAmount: String {
        amount.formatted(.currency(code: currency.rawValue))
    }
}

enum AccountFormatter {
    /// Shortens long account identifiers (e.g. IBANs) to `ES91…1332`.
    static func truncated(_ account: String, keep: Int = 4) -> String {
        guard account.count > keep * 2 + 1 else { return account }
        return "\(account.prefix(keep))…\(account.suffix(keep))"
    }
}
