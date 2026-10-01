import SwiftUI

struct StatusBadge: View {
    let status: TransactionStatus

    var body: some View {
        Text(label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .foregroundStyle(color)
            .background(color.opacity(0.15), in: Capsule())
            .accessibilityLabel(label)
    }

    private var label: LocalizedStringKey {
        switch status {
        case .COMPLETED: return "status.completed".localized
        case .PENDING: return "status.pending".localized
        }
    }

    private var color: Color {
        switch status {
        case .COMPLETED: return .green
        case .PENDING: return .orange
        }
    }
}
