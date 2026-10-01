import SwiftUI

struct OpsView: View {
    private struct Feedback: Identifiable {
        let id = UUID()
        let title: String
        let message: String
    }

    @Environment(\.apiClient) private var api
    @AppStorage(AppSettings.baseURLKey) private var baseURL = AppSettings.defaultBaseURL
    @State private var health: HealthResponse?
    @State private var healthError: String?
    @State private var jobs: [JobInfo] = []
    @State private var jobsError: String?
    @State private var dryRun = true
    @State private var runningJob: String?
    @State private var runningIncident: IncidentScenario?
    @State private var feedback: Feedback?

    var body: some View {
        NavigationStack {
            Form {
                serverSection
                jobsSection
                incidentsSection
            }
            .navigationTitle("ops.title".localized)
            .refreshable { await refresh() }
            .task(id: api.baseURLString) { await refresh() }
            .alert(item: $feedback) { feedback in
                Alert(title: Text(feedback.title), message: Text(feedback.message))
            }
        }
    }

    private var serverSection: some View {
        Section {
            TextField("ops.base_url".localized, text: $baseURL)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(.body.monospaced())
            if let health {
                LabeledContent("ops.health.status".localized) {
                    Label(health.status.uppercased(), systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                }
                LabeledContent("ops.health.transactions".localized, value: String(health.transactions))
            } else if let healthError {
                Label(healthError, systemImage: "xmark.octagon.fill")
                    .foregroundStyle(.red)
                    .font(.footnote)
            } else {
                ProgressView()
            }
            Button("ops.health.refresh".localized) { Task { await refresh() } }
            if baseURL != AppSettings.defaultBaseURL {
                Button("ops.base_url.reset".localized) { baseURL = AppSettings.defaultBaseURL }
            }
        } header: {
            Text("ops.section.server".localized)
        } footer: {
            Text("ops.server.footer".localized)
        }
    }

    private var jobsSection: some View {
        Section("ops.section.jobs".localized) {
            Toggle("ops.jobs.dry_run".localized, isOn: $dryRun)
            if let jobsError {
                Text(jobsError).foregroundStyle(.red).font(.footnote)
            } else if jobs.isEmpty {
                Text("ops.jobs.empty".localized).foregroundStyle(.secondary)
            }
            ForEach(jobs) { job in
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(job.name).font(.body.monospaced().weight(.semibold))
                        Text(job.schedule).font(.caption.monospaced()).foregroundStyle(.secondary)
                        if !job.description.isEmpty {
                            Text(job.description).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if runningJob == job.name {
                        ProgressView()
                    } else {
                        Button("ops.jobs.run".localized) { Task { await run(job) } }
                            .buttonStyle(.bordered)
                            .disabled(runningJob != nil)
                    }
                }
            }
        }
    }

    private var incidentsSection: some View {
        Section {
            ForEach(IncidentScenario.allCases) { scenario in
                Button(role: .destructive) {
                    Task { await trigger(scenario) }
                } label: {
                    HStack {
                        Label(scenario.rawValue, systemImage: "bolt.trianglebadge.exclamationmark")
                            .font(.body.monospaced())
                        Spacer()
                        if runningIncident == scenario { ProgressView() }
                    }
                }
                .disabled(runningIncident != nil)
            }
        } header: {
            Text("ops.section.incidents".localized)
        } footer: {
            Text("ops.incidents.footer".localized)
        }
    }

    private func refresh() async {
        async let healthResult = capture { try await api.health() }
        async let jobsResult = capture { try await api.jobs() }
        let (h, j) = await (healthResult, jobsResult)
        if Task.isCancelled { return }
        switch h {
        case .success(let value): health = value; healthError = nil
        case .failure(let error): health = nil; healthError = error.localizedDescription
        }
        switch j {
        case .success(let value): jobs = value; jobsError = nil
        case .failure(let error): jobs = []; jobsError = error.localizedDescription
        }
    }

    private func run(_ job: JobInfo) async {
        runningJob = job.name
        defer { runningJob = nil }
        do {
            let result = try await api.runJob(name: job.name, dryRun: dryRun)
            let notes = result.notes.isEmpty ? "common.none".localizedString : result.notes.joined(separator: "\n")
            feedback = Feedback(
                title: String(format: "ops.jobs.result_title_format".localizedString, result.job),
                message: String(format: "ops.jobs.result_message_format".localizedString, result.processed, notes)
            )
        } catch {
            feedback = Feedback(title: "ops.jobs.error_title".localizedString, message: error.localizedDescription)
        }
    }

    private func trigger(_ scenario: IncidentScenario) async {
        runningIncident = scenario
        defer { runningIncident = nil }
        do {
            try await api.triggerIncident(scenario)
            feedback = Feedback(
                title: "ops.incidents.unexpected_success_title".localizedString,
                message: scenario.rawValue
            )
        } catch {
            feedback = Feedback(
                title: String(format: "ops.incidents.error_title_format".localizedString, scenario.rawValue),
                message: error.localizedDescription
            )
        }
        await refresh()
    }
}

private func capture<Success>(_ body: () async throws -> Success) async -> Result<Success, Error> {
    do {
        return .success(try await body())
    } catch {
        return .failure(error)
    }
}
