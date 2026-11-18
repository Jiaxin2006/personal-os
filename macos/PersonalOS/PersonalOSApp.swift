import SwiftUI
import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        // A direct executable launch must have the same Dock icon as Finder.
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "png"),
           let icon = NSImage(contentsOf: url) {
            NSApp.applicationIconImage = icon
            NSApp.dockTile.display()
        }
        NSApp.activate(ignoringOtherApps: true)
        // Development instrumentation for checking both themes without changing the system setting.
        if let name = ProcessInfo.processInfo.environment["PERSONAL_OS_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: name == "dark" ? .darkAqua : .aqua)
        }
    }
}

@main
struct PersonalOSApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()
    // Off unless turned on in Settings; the window and SketchyBar already cover the timer.
    @AppStorage("showMenuBarTimer") private var showMenuBarTimer = false
    var body: some Scene {
        WindowGroup("Personal OS", id: "main") {
            MainView().environmentObject(model).frame(minWidth: 960, minHeight: 680).tint(Theme.accent)
        }
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(after: .newItem) {
                Button("刷新数据") { model.refresh() }.keyboardShortcut("r", modifiers: .command)
                Button("导入备份…") { model.importBackup() }.keyboardShortcut("i", modifiers: [.command, .shift])
                Button("导出备份…") { model.exportBackup() }.keyboardShortcut("e", modifiers: [.command, .shift])
            }
        }
        MenuBarExtra(isInserted: $showMenuBarTimer) {
            MenuContent().environmentObject(model)
        } label: {
            Label(model.timer.flag("active") ? clockDuration(model.liveElapsed) : "Personal OS", systemImage: model.timer.flag("running") ? "timer" : "circle.dashed")
        }
    }
}

struct MenuContent: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Text(model.timer.flag("active") ? "\(model.categoryName(model.timer.string("category"))) · \(clockDuration(model.liveElapsed))" : "Plan your effort.")
        if model.timer.flag("active") {
            Button(model.timer.flag("running") ? "暂停" : "继续") { model.timerCommand(model.timer.flag("running") ? "pause" : "resume") }
            Button("保存并结束") { model.timerCommand("stop") }
            Menu("切换活动") {
                ForEach(model.activeCategories, id: \.stringID) { category in
                    Button(category.string("name")) { model.timerCommand("switch", category: category.string("id")) }
                }
            }
        } else {
            Menu("开始活动") {
                ForEach(model.activeCategories, id: \.stringID) { category in
                    Button(category.string("name")) { model.timerCommand("start", category: category.string("id")) }
                }
            }
        }
        Divider()
        Button("打开 Personal OS") { openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        Button("退出 Personal OS") { NSApp.terminate(nil) }
    }
}

extension Dictionary where Key == String, Value == Any {
    var stringID: String { string("id", string("day", string("week_start"))) }
}

struct MainView: View {
    @EnvironmentObject var model: AppModel
    @State private var selection: String? = ProcessInfo.processInfo.environment["PERSONAL_OS_SMOKE_PAGE"] ?? "dashboard"
    @AppStorage("dailySplashEnabled") private var splashEnabled = true
    @AppStorage("lastSplashDay") private var lastSplashDay = ""
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 10) {
                    Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 42, height: 42)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Personal OS").font(.system(size: 18, weight: .bold, design: .rounded)).lineLimit(1)
                        Text("把时间投入长期目标").font(Theme.serif(13, weight: .regular)).lineLimit(1).foregroundStyle(Theme.muted)
                    }
                }.padding(.horizontal, 14).padding(.top, 22)
                List(selection: $selection) {
                    Label("总览", systemImage: "square.grid.2x2").tag("dashboard")
                    Label("时间", systemImage: "timer").tag("time")
                    Label("复盘", systemImage: "text.book.closed").tag("review")
                    Label("设置", systemImage: "slider.horizontal.3").tag("settings")
                }.listStyle(.sidebar).font(.system(size: 15.5, weight: .medium)).environment(\.defaultMinListRowHeight, 40)
                VStack(alignment: .leading, spacing: 6) {
                    Eyebrow(text: "PLAN YOUR EFFORT")
                    Text("随手记录 · 每周复盘").font(.system(size: 12.5))
                    Label("本地保存，无需账户", systemImage: "internaldrive").font(.system(size: 12.5))
                }.foregroundStyle(Theme.muted).padding(16)
            }.navigationSplitViewColumnWidth(min: 214, ideal: 228, max: 270)
        } detail: {
            VStack(spacing: 0) {
                if let error = model.error { messageBanner(error, error: true) }
                if let notice = model.notice { messageBanner(notice, error: false) }
                Group {
                    switch selection {
                    case "time": TimePage()
                    case "review": ReviewPage()
                    case "settings": SettingsPage()
                    default: DashboardPage()
                    }
                }
            }
            .background(Theme.paper)
            .toolbar {
                ToolbarItem(placement: .navigation) {
                    HStack(spacing: 8) {
                        Button { model.changeWeek(-1) } label: { Image(systemName: "chevron.left") }.help("上一周")
                        Text("\(model.currentWeek) — \(model.snapshot.string("week_end"))").font(Theme.number(13, weight: .medium)).monospacedDigit()
                        Button { model.changeWeek(1) } label: { Image(systemName: "chevron.right") }.help("下一周")
                        Button("本周") { model.selectedWeek = nil; model.refresh() }
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    HStack(spacing: 12) {
                        if model.loading { ProgressView().controlSize(.small) }
                        Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }.help("刷新")
                        Button { model.exportBackup() } label: { Image(systemName: "square.and.arrow.up") }.help("导出备份")
                    }
                }
            }
        }
        .toolbar(model.showingSplash ? .hidden : .visible, for: .windowToolbar)
        .overlay {
            if model.showingSplash, let inspiration = model.inspiration {
                DailySplash(inspiration: inspiration) { withAnimation(.easeIn(duration: 0.25)) { model.showingSplash = false } }
                    .ignoresSafeArea().transition(.opacity)
            }
        }
        .onAppear(perform: considerSplash)
        .onChange(of: model.inspiration?.day) { _ in considerSplash() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in considerSplash() }
    }
    // The first window of each day opens on the painting; PERSONAL_OS_SPLASH=1/0 forces it for checks.
    private func considerSplash() {
        guard let day = model.inspiration?.day, !model.showingSplash else { return }
        let forced = ProcessInfo.processInfo.environment["PERSONAL_OS_SPLASH"]
        guard forced != "0", forced == "1" || (splashEnabled && lastSplashDay != day) else { return }
        lastSplashDay = day
        model.showingSplash = true
    }
    private func messageBanner(_ text: String, error: Bool) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: error ? "exclamationmark.circle" : "checkmark.circle").foregroundStyle(error ? Color.red : Theme.met)
            Text(text).font(.callout).textSelection(.enabled)
            Spacer()
            Button { if error { model.error = nil } else { model.notice = nil } } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
        }.padding(12).background(error ? Color.red.opacity(0.08) : Theme.met.opacity(0.1))
    }
}
