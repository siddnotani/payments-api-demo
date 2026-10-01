import SwiftUI

struct NewPaymentView: View {
    private enum Field: Hashable {
        case from, to, amount, reference
    }

    private struct Feedback: Identifiable {
        let id = UUID()
        let title: String
        let message: String
    }

    @Environment(\.apiClient) private var api
    @State private var fromAccount = ""
    @State private var toAccount = ""
    @State private var amount = ""
    @State private var currency: Currency = .EUR
    @State private var reference = ""
    @State private var isSubmitting = false
    @State private var lastCreated: Transaction?
    @State private var feedback: Feedback?
    @FocusState private var focusedField: Field?

    var body: some View {
        NavigationStack {
            Form {
                Section("new_payment.section.accounts".localized) {
                    TextField("new_payment.from_account".localized, text: $fromAccount)
                        .focused($focusedField, equals: .from)
                        .accountInput()
                    TextField("new_payment.to_account".localized, text: $toAccount)
                        .focused($focusedField, equals: .to)
                        .accountInput()
                }

                Section("new_payment.section.amount".localized) {
                    TextField("new_payment.amount".localized, text: $amount)
                        .keyboardType(.decimalPad)
                        .focused($focusedField, equals: .amount)
                    Picker("new_payment.currency".localized, selection: $currency) {
                        ForEach(Currency.allCases) { currency in
                            Text(currency.rawValue).tag(currency)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section {
                    TextField("new_payment.reference".localized, text: $reference)
                        .focused($focusedField, equals: .reference)
                } header: {
                    Text("new_payment.section.reference".localized)
                } footer: {
                    Text("new_payment.reference.footer".localized)
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if isSubmitting {
                                ProgressView()
                            } else {
                                Text("new_payment.submit".localized).bold()
                            }
                            Spacer()
                        }
                    }
                    .disabled(!canSubmit)
                }

                if let lastCreated {
                    Section("new_payment.section.last_created".localized) {
                        LabeledContent("transaction_detail.id".localized) {
                            Text(lastCreated.id)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                        }
                        LabeledContent("transaction_detail.status".localized) {
                            StatusBadge(status: lastCreated.status)
                        }
                        LabeledContent("transaction_detail.amount".localized, value: lastCreated.formattedAmount)
                    }
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("new_payment.title".localized)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("new_payment.fill_sample".localized, action: fillSample)
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("common.done".localized) { focusedField = nil }
                }
            }
            .alert(item: $feedback) { feedback in
                Alert(title: Text(feedback.title), message: Text(feedback.message))
            }
        }
    }

    private var canSubmit: Bool {
        !isSubmitting
            && !fromAccount.trimmingCharacters(in: .whitespaces).isEmpty
            && !toAccount.trimmingCharacters(in: .whitespaces).isEmpty
            && !amount.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func fillSample() {
        fromAccount = "ES9121000418450200051332"
        toAccount = "GB29NWBK60161331926819"
        amount = "125.50"
        currency = .EUR
        reference = "Invoice 42"
    }

    private func submit() async {
        focusedField = nil
        guard let decimal = DecimalInput.parse(amount) else {
            feedback = Feedback(
                title: "new_payment.error.title".localizedString,
                message: "new_payment.error.invalid_amount".localizedString
            )
            return
        }
        let trimmedReference = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        let payload = TransactionCreate(
            fromAccount: fromAccount.trimmingCharacters(in: .whitespaces),
            toAccount: toAccount.trimmingCharacters(in: .whitespaces),
            amount: decimal,
            currency: currency,
            reference: trimmedReference.isEmpty ? nil : trimmedReference
        )

        isSubmitting = true
        defer { isSubmitting = false }
        do {
            let created = try await api.createTransaction(payload)
            lastCreated = created
            amount = ""
            reference = ""
            feedback = Feedback(
                title: "new_payment.success.title".localizedString,
                message: String(
                    format: "new_payment.success.message_format".localizedString,
                    created.id,
                    created.status.rawValue
                )
            )
        } catch is CancellationError {
            return
        } catch let error as APIError where error.statusCode == 422 {
            feedback = Feedback(
                title: "new_payment.error.validation_title".localizedString,
                message: error.localizedDescription
            )
        } catch {
            feedback = Feedback(
                title: "new_payment.error.title".localizedString,
                message: error.localizedDescription
            )
        }
    }
}

enum DecimalInput {
    /// Parses user input using the current locale's decimal separator, falling back to `.`.
    static func parse(_ text: String, locale: Locale = .current) -> Decimal? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        let posix = Locale(identifier: "en_US_POSIX")
        let normalized = trimmed.replacingOccurrences(of: locale.decimalSeparator ?? ".", with: ".")
        guard normalized.allSatisfy({ $0.isNumber || $0 == "." || $0 == "-" }) else { return nil }
        return Decimal(string: normalized, locale: posix)
    }
}

private extension View {
    func accountInput() -> some View {
        textInputAutocapitalization(.characters)
            .autocorrectionDisabled()
            .font(.body.monospaced())
    }
}
