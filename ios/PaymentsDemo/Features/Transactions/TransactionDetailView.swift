import SwiftUI

struct TransactionDetailView: View {
    let transactionID: String

    @Environment(\.apiClient) private var api
    @State private var transaction: Transaction?
    @State private var errorMessage: String?

    var body: some View {
        content
            .navigationTitle("transaction_detail.title".localized)
            .navigationBarTitleDisplayMode(.inline)
            .task { await load() }
            .refreshable { await load() }
    }

    @ViewBuilder
    private var content: some View {
        if let transaction {
            List {
                Section {
                    LabeledContent("transaction_detail.amount".localized, value: transaction.formattedAmount)
                    LabeledContent("transaction_detail.currency".localized, value: transaction.currency.rawValue)
                    LabeledContent("transaction_detail.status".localized) {
                        StatusBadge(status: transaction.status)
                    }
                }
                Section("transaction_detail.accounts".localized) {
                    field("transaction_detail.from_account", transaction.fromAccount)
                    field("transaction_detail.to_account", transaction.toAccount)
                }
                Section {
                    field("transaction_detail.reference", transaction.reference ?? "common.none".localizedString)
                    field(
                        "transaction_detail.created_at",
                        transaction.createdAt.formatted(date: .complete, time: .standard)
                    )
                    field("transaction_detail.id", transaction.id)
                }
            }
        } else if let errorMessage {
            ContentUnavailableView {
                Label("transaction_detail.error.title".localized, systemImage: "exclamationmark.triangle")
            } description: {
                Text(errorMessage)
            } actions: {
                Button("common.retry".localized) { Task { await load() } }
            }
        } else {
            ProgressView()
        }
    }

    private func field(_ key: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(key.localized)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.body.monospaced())
                .textSelection(.enabled)
        }
    }

    private func load() async {
        do {
            transaction = try await api.transaction(id: transactionID)
            errorMessage = nil
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
