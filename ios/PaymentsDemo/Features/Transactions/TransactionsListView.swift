import SwiftUI

struct TransactionsListView: View {
    @Environment(\.apiClient) private var api
    @State private var transactions: [Transaction] = []
    @State private var hasLoaded = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List(transactions) { transaction in
                NavigationLink(value: transaction.id) {
                    TransactionRow(transaction: transaction)
                }
            }
            .overlay { overlay }
            .navigationTitle("transactions.title".localized)
            .navigationDestination(for: String.self) { id in
                TransactionDetailView(transactionID: id)
            }
            .refreshable { await load() }
            .task(id: api.baseURLString) { await load() }
        }
    }

    @ViewBuilder
    private var overlay: some View {
        if let errorMessage, transactions.isEmpty {
            ContentUnavailableView {
                Label("transactions.error.title".localized, systemImage: "wifi.exclamationmark")
            } description: {
                Text(errorMessage)
            } actions: {
                Button("common.retry".localized) { Task { await load() } }
                    .buttonStyle(.borderedProminent)
            }
        } else if !hasLoaded {
            ProgressView()
        } else if transactions.isEmpty {
            ContentUnavailableView(
                "transactions.empty.title".localized,
                systemImage: "tray",
                description: Text("transactions.empty.message".localized)
            )
        }
    }

    private func load() async {
        do {
            let fetched = try await api.listTransactions()
            transactions = fetched.sorted { $0.createdAt > $1.createdAt }
            errorMessage = nil
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
            transactions = []
        }
        hasLoaded = true
    }
}
