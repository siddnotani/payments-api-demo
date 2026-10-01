import SwiftUI

struct TransactionRow: View {
    let transaction: Transaction

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(transaction.formattedAmount)
                    .font(.headline)
                Text(transaction.currency.rawValue)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                StatusBadge(status: transaction.status)
            }
            Text(
                String(
                    format: "transactions.row.route_format".localizedString,
                    AccountFormatter.truncated(transaction.fromAccount),
                    AccountFormatter.truncated(transaction.toAccount)
                )
            )
            .font(.subheadline.monospaced())
            .lineLimit(1)
            .truncationMode(.middle)
            Text(transaction.createdAt.formatted(date: .abbreviated, time: .standard))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}
