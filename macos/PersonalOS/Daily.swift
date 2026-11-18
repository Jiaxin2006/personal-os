import SwiftUI
import AppKit

// The daily verse and painting use offline assets. A personal build can also
// read paintings installed by tools/fetch_paintings.py --local.
struct Poem: Decodable {
    let lines: [String]
    let author: String
    let title: String
    let dynasty: String
    let season: String?
    let name: String?
    // English interface: use the translation and English attribution.
    let translation: [String]?
    let title_en: String?
    let name_en: String?
}

struct Painting: Decodable {
    let met_id: Int
    let title: String
    let artist: String
    let title_en: String?
    let artist_en: String?
    let date: String?
    let credit: String?
    let file: String?
    var caption: String { appUsesEnglish ? "\(title_en ?? title), \(artist_en ?? artist)" : "\(artist)《\(title)》" } // l10n: keep
    var original: String { appUsesEnglish ? date ?? "" : [artist_en, title_en, date].compactMap { $0 }.joined(separator: " · ") }
}

private struct PoemLibrary: Decodable {
    let festivals: [String: Poem]
    let poems: [Poem]
    let authors_en: [String: String]?
    let dynasties_en: [String: String]?
}

struct Inspiration {
    private typealias ArtworkFile = (painting: Painting, url: URL)

    let day: String
    let dateLine: String
    let poem: Poem
    let attribution: String
    let festival: String?
    let greeting: String?
    let painting: Painting?
    let image: NSImage?

    static func make(day: String, timeZone: TimeZone) -> Inspiration? {
        // Development override for checking festival days; `day` stays the real date for caching.
        let dateOverride = ProcessInfo.processInfo.environment["PERSONAL_OS_INSPIRATION_DATE"]
        let shown = dateOverride ?? day
        guard let folder = assetFolder(), let date = noon(of: shown, in: timeZone),
              let data = try? Data(contentsOf: folder.appendingPathComponent("poems.json")),
              let library = try? JSONDecoder().decode(PoemLibrary.self, from: data), !library.poems.isEmpty else { return nil }
        let index = dayNumber(date, timeZone)
        let festivalKey = festival(on: date, timeZone)
        let season = ["winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer",
                      "autumn", "autumn", "autumn", "winter"][calendar(.gregorian, timeZone).component(.month, from: date) - 1]
        let seasonal = stableOrder(library.poems.filter { $0.season == nil || $0.season == season }) { $0.lines.joined() }
        let poem = festivalKey.flatMap { library.festivals[$0] } ?? seasonal[index % seasonal.count]
        var available = paintings(in: folder)
        #if LOCAL_PAINTINGS
        if let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let gallery = support.appendingPathComponent("Personal OS/Local Paintings")
            let bundledIDs = Set(available.map { $0.painting.met_id })
            available += paintings(in: gallery).filter { !bundledIDs.contains($0.painting.met_id) }
        }
        #endif
        // Keep the release rotation independent of changes to the local library.
        let ordered = stableOrder(available) { String($0.painting.met_id) }
        let start = ordered.isEmpty ? 0 : index % ordered.count
        let rotationOrder = Array(ordered[start...]) + ordered.prefix(start)
        #if LOCAL_PAINTINGS
        var rotation = LocalPaintingRotation.load()
        var candidates = rotationOrder
        if dateOverride == nil {
            candidates.sort {
                rotation.priority(for: $0.painting.met_id, on: day) < rotation.priority(for: $1.painting.met_id, on: day)
            }
        }
        #else
        let candidates = rotationOrder
        #endif
        var painting: Painting?, image: NSImage?
        for artwork in candidates {
            guard let loaded = NSImage(contentsOf: artwork.url), loaded.isValid else { continue }
            painting = artwork.painting
            image = loaded
            break
        }
        #if LOCAL_PAINTINGS
        if dateOverride == nil {
            let availableIDs = Set(available.map { $0.painting.met_id })
            let shouldDownload = rotation.record(painting?.met_id, on: day, available: availableIDs)
            rotation.save()
            if shouldDownload { LocalPaintingRotation.downloadBatch() }
        }
        #endif
        let attribution = appUsesEnglish
            ? "\(library.authors_en?[poem.author] ?? poem.author), “\(poem.title_en ?? poem.title)” · \(library.dynasties_en?[poem.dynasty] ?? poem.dynasty)"
            : "\(poem.dynasty)·\(poem.author)《\(poem.title)》" // l10n: keep
        let festival = festivalKey.flatMap { library.festivals[$0] }.map { appUsesEnglish ? $0.name_en ?? $0.name ?? "" : $0.name ?? "" }
        return Inspiration(day: day, dateLine: dateLine(date, timeZone), poem: poem, attribution: attribution, festival: festival,
                           greeting: festival.map { String(localized: "\($0)快乐") }, painting: painting, image: image)
    }

    private static func paintings(in folder: URL) -> [ArtworkFile] {
        let manifest = folder.appendingPathComponent("paintings.json")
        guard let data = try? Data(contentsOf: manifest),
              let entries = try? JSONDecoder().decode([Painting].self, from: data) else { return [] }
        let images = folder.appendingPathComponent("paintings")
        return entries.compactMap { painting in
            let filename = "\(painting.met_id).jpg"
            guard painting.file == filename else { return nil }
            let url = images.appendingPathComponent(filename)
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
            return (painting, url)
        }
    }

    private static func assetFolder() -> URL? {
        var candidates: [URL] = []
        if let custom = ProcessInfo.processInfo.environment["PERSONAL_OS_ASSETS"] { candidates.append(URL(fileURLWithPath: custom)) }
        if let resources = Bundle.main.resourceURL { candidates.append(resources.appendingPathComponent("Daily")) }
        candidates.append(URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("assets"))
        return candidates.first { FileManager.default.fileExists(atPath: $0.appendingPathComponent("poems.json").path) }
    }
    private static func calendar(_ identifier: Calendar.Identifier, _ timeZone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: identifier); calendar.timeZone = timeZone; return calendar
    }
    private static func noon(of day: String, in timeZone: TimeZone) -> Date? {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return calendar(.gregorian, timeZone).date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2], hour: 12))
    }
    private static func dayNumber(_ date: Date, _ timeZone: TimeZone) -> Int {
        let origin = noon(of: "2000-01-01", in: timeZone)!
        return max(0, calendar(.gregorian, timeZone).dateComponents([.day], from: origin, to: date).day ?? 0)
    }
    private static func stableOrder<T>(_ items: [T], key: (T) -> String) -> [T] {
        func fnv(_ text: String) -> UInt32 { text.unicodeScalars.reduce(UInt32(2166136261)) { ($0 ^ $1.value) &* 16777619 } }
        return items.sorted { fnv(key($0)) < fnv(key($1)) }
    }
    private static func festival(on date: Date, _ timeZone: TimeZone) -> String? {
        let lunar = calendar(.chinese, timeZone)
        let today = lunar.dateComponents(in: timeZone, from: date)
        if let tomorrow = lunar.date(byAdding: .day, value: 1, to: date) {
            let next = lunar.dateComponents(in: timeZone, from: tomorrow)
            if next.month == 1 && next.day == 1 && next.isLeapMonth != true { return "new_years_eve" }
        }
        guard today.isLeapMonth != true else { return nil }
        switch (today.month ?? 0, today.day ?? 0) {
        case (1, 1): return "spring_festival"
        case (1, 15): return "lantern"
        case (5, 5): return "dragon_boat"
        case (7, 7): return "qixi"
        case (8, 15): return "mid_autumn"
        case (9, 9): return "double_ninth"
        default: return nil
        }
    }
    private static func dateLine(_ date: Date, _ timeZone: TimeZone) -> String {
        let solar = calendar(.gregorian, timeZone).dateComponents([.month, .day, .weekday], from: date)
        let lunar = calendar(.chinese, timeZone).dateComponents(in: timeZone, from: date)
        if appUsesEnglish {
            let format = DateFormatter(); format.locale = Locale(identifier: "en_US"); format.timeZone = timeZone; format.dateFormat = "EEEE, MMMM d"
            return "\(format.string(from: date)) · lunar \(lunar.isLeapMonth == true ? "leap " : "")month \(lunar.month ?? 1), day \(lunar.day ?? 1)"
        }
        let weekdays = ["日", "一", "二", "三", "四", "五", "六"] // l10n: keep
        let months = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"] // l10n: keep
        let digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"] // l10n: keep
        let d = lunar.day ?? 1
        let lunarDay = d <= 10 ? "初" + digits[d] : d < 20 ? "十" + digits[d - 10] : d == 20 ? "二十" : d < 30 ? "廿" + digits[d - 20] : "三十" // l10n: keep
        let lunarMonth = (lunar.isLeapMonth == true ? "闰" : "") + months[max(0, (lunar.month ?? 1) - 1)] + "月" // l10n: keep
        return "\(solar.month ?? 1)月\(solar.day ?? 1)日 · 星期\(weekdays[(solar.weekday ?? 1) - 1]) · 农历\(lunarMonth)\(lunarDay)" // l10n: keep
    }
}

private struct Artwork: View {
    let image: NSImage?
    var body: some View {
        if let image = image {
            Image(nsImage: image).resizable().scaledToFill()
        } else {
            LinearGradient(colors: [Color(red: 0.42, green: 0.40, blue: 0.95), Color(red: 0.20, green: 0.17, blue: 0.62)],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
        }
    }
}

struct PoemLines: View {
    let poem: Poem
    let size: CGFloat
    var body: some View {
        let lines = appUsesEnglish ? poem.translation ?? poem.lines : poem.lines
        VStack(alignment: .leading, spacing: size * (appUsesEnglish ? 0.22 : 0.45)) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                if appUsesEnglish {
                    Text(line).font(.system(size: size * 0.82, weight: .regular, design: .serif)).italic()
                } else {
                    Text(line).font(Theme.verse(size))
                }
            }
        }
    }
}

// Top of the overview: today's painting behind today's verse. Click to view it whole.
struct DailyHero: View {
    let inspiration: Inspiration
    let open: () -> Void
    var body: some View {
        Color.clear.frame(height: 236)
            .overlay(Artwork(image: inspiration.image))
            .overlay(LinearGradient(stops: [.init(color: .black.opacity(0.66), location: 0), .init(color: .black.opacity(0.32), location: 0.5),
                                            .init(color: .black.opacity(0.05), location: 1)], startPoint: .leading, endPoint: .trailing))
            .overlay(alignment: .leading) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 8) {
                        Text(inspiration.dateLine).font(.system(size: 12, weight: .medium)).tracking(0.6)
                        if let festival = inspiration.festival {
                            Text(festival).font(Theme.serif(12)).padding(.horizontal, 7).padding(.vertical, 2).background(.white.opacity(0.2), in: Capsule())
                        }
                    }.foregroundStyle(.white.opacity(0.82))
                    PoemLines(poem: inspiration.poem, size: appUsesEnglish ? 22 : 25).foregroundStyle(.white)
                    Text((appUsesEnglish ? "— " : "—— ") + inspiration.attribution).font(Theme.serif(13, weight: .regular)).foregroundStyle(.white.opacity(0.78))
                }.padding(.horizontal, 30).shadow(color: .black.opacity(0.35), radius: 8)
            }
            .overlay(alignment: .bottomTrailing) {
                if let painting = inspiration.painting {
                    Label(painting.caption, systemImage: "photo.artframe").font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.white.opacity(0.9)).padding(.horizontal, 10).padding(.vertical, 5)
                        .background(.black.opacity(0.28), in: Capsule()).padding(14)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .onTapGesture(perform: open)
            .help("查看今日画作与诗词")
    }
}

// Shown on the first window of each day (and from the hero): the painting whole,
// over a blurred copy of itself, with the verse and the museum credit.
struct DailySplash: View {
    let inspiration: Inspiration
    let dismiss: () -> Void
    @State private var appeared = false
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Opaque blur, so the window behind never shows through at the edges.
                Color.black
                Artwork(image: inspiration.image).frame(width: geometry.size.width, height: geometry.size.height)
                    .blur(radius: 46, opaque: true).clipped().overlay(Color.black.opacity(0.5))
                HStack(alignment: .center, spacing: 52) {
                    if let image = inspiration.image {
                        Image(nsImage: image).resizable().scaledToFit()
                            .frame(maxWidth: geometry.size.width * 0.56, maxHeight: geometry.size.height * 0.76)
                            .shadow(color: .black.opacity(0.45), radius: 28, y: 14)
                    }
                    VStack(alignment: .leading, spacing: 0) {
                        Text(inspiration.dateLine).font(.system(size: 13, weight: .medium)).tracking(0.8).foregroundStyle(.white.opacity(0.75))
                        if let greeting = inspiration.greeting {
                            Text(greeting).font(Theme.serif(15)).foregroundStyle(.white).padding(.top, 10)
                        }
                        PoemLines(poem: inspiration.poem, size: 32).foregroundStyle(.white).padding(.top, 30)
                        Text((appUsesEnglish ? "— " : "—— ") + inspiration.attribution).font(Theme.serif(15, weight: .regular)).foregroundStyle(.white.opacity(0.8)).padding(.top, 22)
                        if let painting = inspiration.painting {
                            Rectangle().fill(.white.opacity(0.25)).frame(width: 36, height: 1).padding(.top, 40)
                            Text(painting.caption).font(Theme.serif(14)).foregroundStyle(.white.opacity(0.9)).padding(.top, 16)
                            Text(painting.original).font(.system(size: 11)).foregroundStyle(.white.opacity(0.6)).padding(.top, 5)
                            Text(painting.credit ?? "").font(.system(size: 10.5)).foregroundStyle(.white.opacity(0.45)).padding(.top, 3)
                        }
                        Button(action: dismiss) {
                            Text("开始今天").font(.system(size: 14, weight: .semibold)).padding(.horizontal, 22).padding(.vertical, 9)
                                .background(.white.opacity(0.92), in: Capsule()).foregroundStyle(Color(red: 0.2, green: 0.17, blue: 0.55))
                        }.buttonStyle(.plain).keyboardShortcut(.defaultAction).padding(.top, 38)
                    }.frame(maxWidth: 380, alignment: .leading)
                }.padding(56).frame(width: geometry.size.width, height: geometry.size.height)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture(perform: dismiss)
        .onExitCommand(perform: dismiss)
        .opacity(appeared ? 1 : 0)
        .onAppear { withAnimation(.easeOut(duration: 0.6)) { appeared = true } }
    }
}
