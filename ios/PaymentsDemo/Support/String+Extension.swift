import SwiftUI

extension String {
    /// For SwiftUI `Text` and other views accepting `LocalizedStringKey`.
    var localized: LocalizedStringKey { LocalizedStringKey(self) }

    /// For contexts needing a resolved `String` (alerts, view models, formatting).
    var localizedString: String {
        NSLocalizedString(self, comment: "\(self)_comment")
    }
}
