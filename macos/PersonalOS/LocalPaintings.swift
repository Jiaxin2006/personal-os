#if LOCAL_PAINTINGS
import Foundation

struct LocalPaintingRotation: Codable {
    private static let storageKey = "localPaintingRotation"
    private static let worker = DispatchQueue(label: "PersonalOS.paintings", qos: .utility)
    private var shownIDs: Set<Int> = []
    private var selectedID: Int?
    private var selectedDay: String?
    private var lastDownloadDay: String?

    static func load(from defaults: UserDefaults = .standard) -> Self {
        guard let data = defaults.data(forKey: storageKey),
              let rotation = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return rotation
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(try? JSONEncoder().encode(self), forKey: Self.storageKey)
    }

    func priority(for id: Int, on day: String) -> Int {
        if day == selectedDay && id == selectedID { return 0 }
        return shownIDs.contains(id) ? 2 : 1
    }

    mutating func record(_ id: Int?, on day: String, available: Set<Int>) -> Bool {
        shownIDs.formIntersection(available)
        if let id = id {
            shownIDs.insert(id)
            selectedID = id
            selectedDay = day
        }
        guard available.subtracting(shownIDs).count <= 5, day != lastDownloadDay else { return false }
        lastDownloadDay = day
        return true
    }

    static func downloadBatch() {
        guard let python = pythonInterpreter(),
              let daily = Bundle.main.resourceURL?.appendingPathComponent("Daily") else { return }
        worker.async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = ["-B", daily.appendingPathComponent("fetch_paintings.py").path,
                                 "--top-up", daily.appendingPathComponent("paintings.json").path]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                process.waitUntilExit()
                if process.terminationStatus != 0 { NSLog("Personal OS could not replenish its painting library today.") }
            } catch {
                NSLog("Unable to start Personal OS painting download: %@", error.localizedDescription)
            }
        }
    }
}
#endif
