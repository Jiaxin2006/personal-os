import Foundation
import SwiftUI
import AppKit
import UniformTypeIdentifiers

typealias JSON = [String: Any]

// macOS resolves the app language on launch. Translations live in Localization/.
let appUsesEnglish = Bundle.main.preferredLocalizations.first?.hasPrefix("en") ?? false

enum AppLanguage: String {
    case system = ""
    case chinese = "zh-Hans"
    case english = "en"

    private static let preference = "AppleLanguages"

    static var selected: Self {
        guard let id = Bundle.main.bundleIdentifier,
              let languages = UserDefaults.standard.persistentDomain(forName: id)?[preference] as? [String],
              let language = languages.first else { return .system }
        if language.hasPrefix("en") { return .english }
        if language == "zh" || language.hasPrefix("zh-Hans") { return .chinese }
        return .system
    }

    func save() {
        if self == .system {
            UserDefaults.standard.removeObject(forKey: Self.preference)
        } else {
            UserDefaults.standard.set([rawValue], forKey: Self.preference)
        }
    }
}

func pythonInterpreter() -> String? {
    let bundled = Bundle.main.resourceURL?.appendingPathComponent("python/bin/python3").path
    let paths = [ProcessInfo.processInfo.environment["PERSONAL_OS_PYTHON"], bundled,
                 "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
    return paths.compactMap { $0 }.first(where: FileManager.default.isExecutableFile(atPath:))
}

extension Dictionary where Key == String, Value == Any {
    func string(_ key: String, _ fallback: String = "") -> String { self[key] as? String ?? fallback }
    func number(_ key: String, _ fallback: Double = 0) -> Double { (self[key] as? NSNumber)?.doubleValue ?? fallback }
    func flag(_ key: String, _ fallback: Bool = false) -> Bool { self[key] as? Bool ?? fallback }
    func object(_ key: String) -> JSON { self[key] as? JSON ?? [:] }
    func objects(_ key: String) -> [JSON] { self[key] as? [JSON] ?? [] }
}

func duration(_ seconds: Double) -> String {
    let minutes = boundedNonnegativeInt(seconds) / 60
    return minutes >= 60 ? String(localized: "\(minutes / 60)小时 \(minutes % 60)分") : String(localized: "\(minutes)分")
}
func compactDuration(_ seconds: Double) -> String { String(format: "%.1fh", seconds / 3600) }
func clockDuration(_ seconds: Double) -> String {
    let s = boundedNonnegativeInt(seconds); return String(format: "%02d:%02d:%02d", s / 3600, s % 3600 / 60, s % 60)
}
func boundedNonnegativeInt(_ value: Double) -> Int {
    guard value.isFinite else { return 0 }
    return Int(min(max(0, value), Double(Int.max / 2)))
}
func validatedSeconds(_ text: String, unit: Double, maximum: Double, allowZero: Bool = false) -> Int? {
    guard let value = Double(text), value.isFinite, value <= maximum,
          (allowZero ? value >= 0 : value > 0) else { return nil }
    return Int(value * unit)
}
func localDate(_ date: Date) -> String {
    let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date)
}
func parsedDate(_ string: String) -> Date {
    let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.date(from: string) ?? Date()
}
func categoryColor(_ id: String) -> Color { Theme.category(id) }
func goalStatus(_ goal: JSON) -> String {
    switch goal.string("status") {
    case "met": return goal.string("kind") == "maximum_duration" ? String(localized: "当前未超限") : String(localized: "已达到")
    case "over": return String(localized: "超出范围")
    case "observing": return String(localized: "仅观察")
    default: return String(localized: "尚有差距")
    }
}
func goalAmount(_ goal: JSON) -> String {
    if goal.string("unit") == "days" { return String(localized: "\(Int(goal.number("actual"))) / \(Int(goal.number("target"))) 天") }
    let actual = duration(goal.number("actual"))
    if goal.string("kind") == "observe" { return actual }
    if goal.string("kind") == "duration_range" { return String(localized: "\(actual) · 目标 \(compactDuration(goal.number("minimum")))–\(compactDuration(goal.number("maximum")))") }
    return "\(actual) / \(duration(goal.number("target")))"
}

final class AppModel: ObservableObject {
    @Published var snapshot: JSON = [:]
    @Published var error: String?
    @Published var notice: String?
    @Published var loading = false
    @Published var selectedWeek: String?
    @Published var inspiration: Inspiration? = Inspiration.make(day: localDate(Date()), timeZone: .current)
    @Published var showingSplash = false
    // Advances every second only while a timer runs, so elapsed time updates without a backend call.
    @Published private var clock = Date()
    private var snapshotAt = Date()
    private var lastBackendPulse = Date()
    private let worker = DispatchQueue(label: "PersonalOS.backend")
    private var pulseTimer: Timer?
    private var observers: [NSObjectProtocol] = []
    private var refreshing = false
    private var sleeping = false
    private var smokeScheduled = false
    var profile: JSON { snapshot.object("profile") }
    var stats: JSON { snapshot.object("statistics") }
    var timer: JSON { snapshot.object("timer") }
    var categories: [JSON] { profile.objects("categories") }
    var activeCategories: [JSON] { categories.filter { !$0.flag("archived") } }
    var goals: [JSON] { stats.objects("goals") }
    var tasks: [JSON] { snapshot.objects("tasks") }
    var currentWeek: String { snapshot.string("week_start", localDate(Date())) }
    var currentDate: String { snapshot.string("today", localDate(Date())) }
    func categoryName(_ id: String) -> String { categories.first { $0.string("id") == id }?.string("name") ?? id }
    var liveElapsed: Double {
        let base = timer.number("elapsed_seconds")
        return timer.flag("running") ? base + max(0, clock.timeIntervalSince(snapshotAt)) : base
    }

    init() {
        refresh()
        pulseTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.pulse() }
        observers.append(NotificationCenter.default.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.refresh(quiet: true)
        })
        let center = NSWorkspace.shared.notificationCenter
        observers.append(center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in
            self?.sleeping = true
            self?.send(["action": "timer", "command": "sleep"], quiet: true)
        })
        observers.append(center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.sleeping = false
            self?.send(["action": "timer", "command": "wake"], quiet: true)
        })
    }
    deinit {
        pulseTimer?.invalidate()
        observers.forEach { NSWorkspace.shared.notificationCenter.removeObserver($0); NotificationCenter.default.removeObserver($0) }
    }
    // Each backend call starts Python, so poll sparingly: a running timer needs a
    // heartbeat well inside the backend's 60-second stale limit; idle polling only
    // picks up changes made from SketchyBar.
    private func pulse() {
        let running = timer.flag("running")
        if running { clock = Date() }
        guard !refreshing, !loading, !sleeping, Date().timeIntervalSince(lastBackendPulse) >= (running ? 10 : 20) else { return }
        lastBackendPulse = Date()
        if running { send(["action": "timer", "command": "tick"], quiet: true) } else { refresh(quiet: true) }
    }

    private func backendRoot() throws -> URL {
        var candidates: [URL] = []
        if let custom = ProcessInfo.processInfo.environment["PERSONAL_OS_BACKEND"] {
            let u = URL(fileURLWithPath: custom); candidates.append(custom.hasSuffix(".py") ? u.deletingLastPathComponent().deletingLastPathComponent() : u)
        }
        if let resources = Bundle.main.resourceURL { candidates.append(resources.appendingPathComponent("backend")) }
        candidates.append(URL(fileURLWithPath: FileManager.default.currentDirectoryPath))
        if let root = candidates.first(where: { FileManager.default.fileExists(atPath: $0.appendingPathComponent("personal_os/cli.py").path) }) { return root }
        throw NSError(domain: "PersonalOS", code: 1, userInfo: [NSLocalizedDescriptionKey: String(localized: "找不到本地业务组件，请重新构建 Personal OS 应用。")])
    }
    private func execute(_ payload: JSON) throws -> JSON {
        let root = try backendRoot()
        let process = Process()
        let environment = ProcessInfo.processInfo.environment
        guard let python = pythonInterpreter() else {
            throw NSError(domain: "PersonalOS", code: 2, userInfo: [NSLocalizedDescriptionKey: String(localized: "需要 Python 3.9 或更新版本，请先安装 Python。")])
        }
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-B", root.appendingPathComponent("personal_os/cli.py").path]
        process.currentDirectoryURL = root
        var env = environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (env["PATH"] ?? "")
        env["PYTHONUTF8"] = "1"
        env["PERSONAL_OS_LANGUAGE"] = appUsesEnglish ? "en" : "zh"
        process.environment = env
        let input = Pipe(), output = Pipe(), errors = Pipe()
        process.standardInput = input; process.standardOutput = output; process.standardError = errors
        try process.run()
        let watchdog = DispatchWorkItem { if process.isRunning { process.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + 25, execute: watchdog)
        try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: payload))
        try input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        let errorData = errors.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit(); watchdog.cancel()
        let value = (try? JSONSerialization.jsonObject(with: data)) as? JSON
        if let failure = value?["error"] as? String { throw NSError(domain: "PersonalOS", code: 3, userInfo: [NSLocalizedDescriptionKey: failure]) }
        guard process.terminationStatus == 0, let result = value else {
            let stderr = String(data: errorData, encoding: .utf8) ?? ""
            throw NSError(domain: "PersonalOS", code: 4, userInfo: [NSLocalizedDescriptionKey: stderr.isEmpty ? String(localized: "本地组件未返回有效结果，请重试。") : String(stderr.suffix(1600))])
        }
        return result
    }
    func refresh(quiet: Bool = false) {
        guard !refreshing else { return }; refreshing = true
        if !quiet { loading = true }
        var request: JSON = ["action": "snapshot"]
        if let week = selectedWeek { request["week_start"] = week }
        let requested = Date()
        worker.async { [weak self] in
            guard let self = self else { return }
            do {
                let data = try self.execute(request)
                DispatchQueue.main.async {
                    // The backend measured elapsed time when the request started.
                    self.snapshotAt = requested; self.clock = Date(); self.lastBackendPulse = Date()
                    self.snapshot = data; self.loading = false; self.refreshing = false
                    let today = data["today"] as? String ?? localDate(Date())
                    if self.inspiration?.day != today {
                        let zone = TimeZone(identifier: (data["profile"] as? JSON)?.string("timezone") ?? "") ?? .current
                        self.inspiration = Inspiration.make(day: today, timeZone: zone)
                    }
                    self.scheduleSmokeCapture()
                }
            } catch {
                DispatchQueue.main.async {
                    self.error = error.localizedDescription; self.loading = false; self.refreshing = false
                    self.writeSmokeFailure(error.localizedDescription)
                }
            }
        }
    }
    func send(_ payload: JSON, quiet: Bool = false, message: String? = nil, completion: (() -> Void)? = nil) {
        if !quiet { loading = true; error = nil }
        worker.async { [weak self] in
            guard let self = self else { return }
            do {
                _ = try self.execute(payload)
                DispatchQueue.main.async {
                    self.loading = false
                    if let message = message { self.notice = message }
                    completion?(); self.refresh(quiet: true)
                }
            } catch {
                DispatchQueue.main.async {
                    self.loading = false; self.error = error.localizedDescription
                    self.writeSmokeFailure(error.localizedDescription)
                }
            }
        }
    }
    func timerCommand(_ command: String, category: String? = nil) {
        var p: JSON = ["action": "timer", "command": command]
        if let category = category { p["category"] = category }
        send(p)
    }
    func changeWeek(_ offset: Int) {
        let date = parsedDate(currentWeek)
        selectedWeek = localDate(Calendar.current.date(byAdding: .day, value: offset * 7, to: date) ?? date)
        refresh()
    }
    func saveProfile(_ profile: JSON, completion: (() -> Void)? = nil) { send(["action": "save_profile", "profile": profile], message: String(localized: "设置已保存"), completion: completion) }
    func replaceProfileItem(_ collection: String, item: JSON, completion: (() -> Void)? = nil) {
        var value = profile; var items = value.objects(collection)
        if let i = items.firstIndex(where: { $0.string("id") == item.string("id") }) { items[i] = item }
        else { items.append(item) }
        value[collection] = items; saveProfile(value, completion: completion)
    }
    func importBackup() {
        guard !timer.flag("active") else {
            error = String(localized: "请先保存或结束当前计时，再导入备份。")
            return
        }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]
        panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.title = String(localized: "导入 Personal OS 备份"); panel.prompt = String(localized: "导入")
        panel.message = String(localized: "配置、补记、周期任务和复盘将在新工作区恢复，现有数据会保留。计时继续使用当前记录。")
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.send(["action": "import", "path": url.path], message: String(localized: "备份已在新工作区恢复；计时继续使用当前记录"), completion: { self?.selectedWeek = nil })
        }
    }
    // Opt-in development instrumentation. It captures only this app's own view
    // hierarchy and does not use screen recording or Accessibility APIs.
    private var smokeOutput: String? {
        guard let value = ProcessInfo.processInfo.environment["PERSONAL_OS_SMOKE_OUTPUT"], !value.isEmpty else { return nil }
        return value
    }
    private func scheduleSmokeCapture() {
        guard smokeOutput != nil, !smokeScheduled else { return }
        smokeScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in self?.captureOwnWindow(attempt: 0) }
    }
    private func captureOwnWindow(attempt: Int) {
        guard let output = smokeOutput else { return }
        guard let window = NSApp.windows.first(where: { $0.isVisible && ($0.contentView?.bounds.width ?? 0) > 600 }), let view = window.contentView else {
            if attempt < 8 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.captureOwnWindow(attempt: attempt + 1) }
            } else { writeSmokeFailure("No visible Personal OS main window available for smoke capture.") }
            return
        }
        window.displayIfNeeded(); view.layoutSubtreeIfNeeded()
        do {
            guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
                throw NSError(domain: "PersonalOS.Smoke", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unable to create bitmap for own application view."])
            }
            view.cacheDisplay(in: view.bounds, to: bitmap)
            guard let png = bitmap.representation(using: .png, properties: [:]) else {
                throw NSError(domain: "PersonalOS.Smoke", code: 2, userInfo: [NSLocalizedDescriptionKey: "Unable to encode own application view as PNG."])
            }
            let file = URL(fileURLWithPath: output)
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try png.write(to: URL(fileURLWithPath: output + ".png"), options: .atomic)
            try JSONSerialization.data(withJSONObject: snapshot, options: [.prettyPrinted, .sortedKeys])
                .write(to: URL(fileURLWithPath: output + ".json"), options: .atomic)
            NSApp.terminate(nil)
        } catch { writeSmokeFailure(error.localizedDescription) }
    }
    private func writeSmokeFailure(_ message: String) {
        guard let output = smokeOutput else { return }
        let file = URL(fileURLWithPath: output + ".error")
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? message.write(to: file, atomically: true, encoding: .utf8)
        NSApp.terminate(nil)
    }
    func exportBackup() {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.json]; panel.nameFieldStringValue = "PersonalOS-backup-\(currentDate).json"
        panel.title = String(localized: "导出 Personal OS 备份"); panel.prompt = String(localized: "导出")
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            // NSSavePanel has already asked before replacing an existing file.
            self?.send(["action": "export", "path": url.path, "overwrite": true], message: String(localized: "备份已导出到 \(url.lastPathComponent)"))
        }
    }
}
