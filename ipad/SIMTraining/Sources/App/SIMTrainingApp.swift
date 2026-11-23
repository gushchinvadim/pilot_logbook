import SwiftUI

@main struct SIMTrainingApp: App {
    @StateObject private var state = AppState()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(state).tint(Color(red: 0.02, green: 0.43, blue: 0.65))
                .task { await state.restore() }
        }
    }
}
