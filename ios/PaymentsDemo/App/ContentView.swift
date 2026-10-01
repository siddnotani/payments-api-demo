import SwiftUI

struct ContentView: View {
    @AppStorage(AppSettings.baseURLKey) private var baseURL = AppSettings.defaultBaseURL

    var body: some View {
        TabView {
            TransactionsListView()
                .tabItem { Label("tab.transactions".localized, systemImage: "list.bullet.rectangle") }
            NewPaymentView()
                .tabItem { Label("tab.new_payment".localized, systemImage: "plus.circle") }
            OpsView()
                .tabItem { Label("tab.ops".localized, systemImage: "wrench.and.screwdriver") }
        }
        .environment(\.apiClient, APIClient(baseURLString: baseURL))
    }
}

#Preview {
    ContentView()
}
