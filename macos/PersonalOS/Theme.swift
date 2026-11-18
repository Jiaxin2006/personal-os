import SwiftUI
import AppKit

// One visual language: ink on rice paper in light mode, paper on ink in dark mode,
// with the indigo of the app icon as the single accent.
enum Theme {
    static let accent = dynamic(light: rgb(0x4B, 0x46, 0xC8), dark: rgb(0x8E, 0x8A, 0xFF))
    static let paper = dynamic(light: rgb(0xF6, 0xF3, 0xEC), dark: rgb(0x14, 0x14, 0x18))
    static let card = dynamic(light: rgb(0xFF, 0xFE, 0xFB), dark: rgb(0x1E, 0x1E, 0x23))
    static let ink = dynamic(light: rgb(0x1F, 0x1C, 0x19), dark: rgb(0xEE, 0xEA, 0xE2))
    static let muted = dynamic(light: rgb(0x7A, 0x74, 0x6B), dark: rgb(0x9C, 0x97, 0x8E))
    static let hairline = dynamic(light: NSColor(white: 0, alpha: 0.07), dark: NSColor(white: 1, alpha: 0.08))
    static let track = dynamic(light: NSColor(white: 0, alpha: 0.06), dark: NSColor(white: 1, alpha: 0.09))
    static let met = dynamic(light: rgb(0x3E, 0x8E, 0x6E), dark: rgb(0x6C, 0xC4, 0x9C))
    static let warning = dynamic(light: rgb(0xC0, 0x6A, 0x2B), dark: rgb(0xE9, 0x9A, 0x55))

    // Muted traditional colours: 靛青 石青 竹青 胭脂 紫藤 藤黄 墨灰.
    private static let known: [String: Color] = [
        "research": rgbColor(0x4B, 0x46, 0xC8), "course": rgbColor(0x2E, 0x7D, 0xAF),
        "biology": rgbColor(0x3E, 0x8E, 0x6E), "social": rgbColor(0xC0, 0x48, 0x5A),
        "other_work": rgbColor(0x8A, 0x63, 0xB8), "reading": rgbColor(0xD3, 0x8B, 0x2C),
        "uncategorized": rgbColor(0x8C, 0x87, 0x80),
    ]
    private static let extra = [rgbColor(0x5B, 0x8F, 0xA8), rgbColor(0xA8, 0x6B, 0x4F), rgbColor(0x6E, 0x7F, 0x3A),
                                rgbColor(0xB0, 0x5F, 0x8C), rgbColor(0x4F, 0x6D, 0x8F), rgbColor(0x9A, 0x82, 0x3E)]
    static func category(_ id: String) -> Color {
        if let color = known[id] { return color }
        // Stable across launches (String.hashValue is not).
        let hash = id.unicodeScalars.reduce(UInt32(2166136261)) { ($0 ^ $1.value) &* 16777619 }
        return extra[Int(hash % UInt32(extra.count))]
    }

    static func serif(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font { .custom("Songti SC", size: size).weight(weight) }
    static func verse(_ size: CGFloat) -> Font { .custom(NSFont(name: "Kaiti SC", size: size) != nil ? "Kaiti SC" : "Songti SC", size: size) }
    static func number(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font { .system(size: size, weight: weight, design: .rounded) }

    private static func rgb(_ r: Int, _ g: Int, _ b: Int) -> NSColor {
        NSColor(srgbRed: CGFloat(r) / 255, green: CGFloat(g) / 255, blue: CGFloat(b) / 255, alpha: 1)
    }
    private static func rgbColor(_ r: Int, _ g: Int, _ b: Int) -> Color { Color(nsColor: rgb(r, g, b)) }
    private static func dynamic(light: NSColor, dark: NSColor) -> Color {
        Color(nsColor: NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light })
    }
}

struct Eyebrow: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 10.5, weight: .semibold)).tracking(1.6).foregroundStyle(Theme.muted)
    }
}

struct StatusChip: View {
    let text: String
    let color: Color
    var body: some View {
        Text(text).font(.system(size: 11, weight: .medium)).foregroundStyle(color)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.12), in: Capsule())
    }
}

struct MeterBar: View {
    let value: Double
    let color: Color
    var height: CGFloat = 6
    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.track)
                Capsule().fill(color).frame(width: max(value > 0 ? height : 0, geometry.size.width * min(1, max(0, value))))
            }
        }.frame(height: height)
    }
}
