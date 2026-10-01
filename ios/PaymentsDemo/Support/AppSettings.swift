import SwiftUI

enum AppSettings {
    /// UserDefaults key for the API base URL. Can be overridden at launch with
    /// `-api_base_url http://host:port`.
    static let baseURLKey = "api_base_url"
    static let defaultBaseURL = "http://localhost:8000"
}

private struct APIClientKey: EnvironmentKey {
    static let defaultValue = APIClient(baseURLString: AppSettings.defaultBaseURL)
}

extension EnvironmentValues {
    var apiClient: APIClient {
        get { self[APIClientKey.self] }
        set { self[APIClientKey.self] = newValue }
    }
}
