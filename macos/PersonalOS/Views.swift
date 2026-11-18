import SwiftUI
import AppKit
import Charts

struct Card<Content: View>: View {
    var title: LocalizedStringKey?
    @ViewBuilder var content: Content
    init(_ title: LocalizedStringKey? = nil, @ViewBuilder content: () -> Content) { self.title = title; self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let title = title { Text(title).font(Theme.serif(16)).foregroundStyle(Theme.ink) }
            content
        }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Theme.hairline, lineWidth: 1))
            .shadow(color: .black.opacity(0.035), radius: 12, y: 4)
    }
}
struct PageHeading: View {
    let title: LocalizedStringKey, subtitle: LocalizedStringKey
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(Theme.serif(30, weight: .bold)).foregroundStyle(Theme.ink)
            Text(subtitle).font(.subheadline).foregroundStyle(Theme.muted)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
struct SectionHeading: View {
    let title: LocalizedStringKey
    var detail = ""
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title).font(Theme.serif(20, weight: .bold)).foregroundStyle(Theme.ink)
            if !detail.isEmpty { Text(detail).font(.caption).foregroundStyle(Theme.muted) }
        }
    }
}
struct EmptyNote: View {
    let text: LocalizedStringKey
    var body: some View { Text(text).font(.callout).foregroundStyle(Theme.muted).padding(.vertical, 16).frame(maxWidth: .infinity, alignment: .leading) }
}
func goalColor(_ goal: JSON) -> Color {
    switch goal.string("status") {
    case "met": return Theme.met
    case "over": return Theme.warning
    case "observing": return Theme.muted
    default: return Theme.accent
    }
}
struct GoalRow: View {
    let goal: JSON
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(goal.string("name")).font(.system(size: 13.5, weight: .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                Text(goal.string("strength") == "hard" ? "硬性" : goal.string("strength") == "flexible" ? "弹性" : "观察")
                    .font(.system(size: 10.5, weight: .medium)).foregroundStyle(Theme.muted)
            }
            Text(goalAmount(goal)).font(Theme.number(21)).monospacedDigit().foregroundStyle(Theme.ink)
            MeterBar(value: goal.number("progress"), color: goalColor(goal))
            StatusChip(text: goalStatus(goal), color: goalColor(goal))
        }
    }
}
struct StatCard: View {
    let label: String, value: String, detail: String, icon: String
    let color: Color
    var progress: Double?
    var body: some View {
        Card {
            HStack {
                Eyebrow(text: label)
                Spacer()
                Image(systemName: icon).font(.system(size: 12, weight: .semibold)).foregroundStyle(color)
                    .frame(width: 28, height: 28).background(color.opacity(0.12), in: Circle())
            }
            Text(value).font(Theme.number(34)).monospacedDigit().foregroundStyle(Theme.ink)
            if let progress = progress { MeterBar(value: progress, color: color, height: 4) }
            Text(detail).font(.caption).foregroundStyle(Theme.muted)
        }
    }
}

struct DashboardPage: View {
    @EnvironmentObject var model: AppModel
    var visibleTasks: [JSON] { model.tasks.filter { $0.flag("is_visible") && $0.string("status") == "pending" && !$0.flag("is_overdue") } }
    var overdueTasks: [JSON] { model.tasks.filter { $0.flag("is_overdue") && $0.string("status") == "pending" } }
    func goal(_ id: String) -> JSON? { model.goals.first { $0.string("id") == id } }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let inspiration = model.inspiration {
                    DailyHero(inspiration: inspiration) { withAnimation(.easeOut(duration: 0.3)) { model.showingSplash = true } }
                } else {
                    PageHeading(title: "把投入放在重要的事上", subtitle: "每周看方向，不必把每一天排满。")
                }
                SectionHeading(title: "本周投入")
                HStack(spacing: 14) {
                    let work = goal("total-work-weekly")
                    StatCard(label: String(localized: "总工作投入"), value: compactDuration(model.stats.number("work_seconds")),
                             detail: work.map { String(localized: "距目标还差 \(duration(max(0, $0.number("target") - $0.number("actual"))))") } ?? String(localized: "本周已保存投入"),
                             icon: "briefcase", color: Theme.accent, progress: work?.number("progress"))
                    let researchDays = goal("research-weekly-frequency")
                    StatCard(label: String(localized: "\(model.categoryName("research"))投入"), value: compactDuration(model.stats.number("research_seconds")),
                             detail: String(localized: "\(Int(model.stats.number("research_days"))) 个有效投入日") + (researchDays.map { String(localized: " · 目标 \(Int($0.number("target"))) 天") } ?? ""),
                             icon: "sparkle.magnifyingglass", color: Theme.category("research"), progress: goal("research-weekly-duration")?.number("progress"))
                    let reading = goal("reading-weekly-frequency")
                    StatCard(label: String(localized: "\(model.categoryName("reading"))天数"), value: String(localized: "\(Int(model.stats.number("reading_days"))) 天"),
                             detail: reading.map { String(localized: "目标 \(Int($0.number("target"))) 天，各日累计 \(Int($0.number("minimum_daily_seconds") / 60)) 分钟") } ?? String(localized: "当天达标才算一天"),
                             icon: "book", color: Theme.category("reading"), progress: reading?.number("progress"))
                }
                if model.timer.flag("active") {
                    HStack(spacing: 12) {
                        Circle().fill(model.timer.flag("running") ? categoryColor(model.timer.string("category")) : Theme.muted).frame(width: 8, height: 8)
                        Text(model.categoryName(model.timer.string("category"))).font(.system(size: 13, weight: .semibold))
                        Text(clockDuration(model.liveElapsed)).font(Theme.number(15, weight: .medium)).monospacedDigit()
                        if !model.timer.flag("running") { Text("已暂停").font(.caption).foregroundStyle(Theme.muted) }
                        Spacer()
                        Text("本次尚未保存，不计入正式进度").font(.caption).foregroundStyle(Theme.muted)
                    }.padding(.horizontal, 18).padding(.vertical, 14)
                    .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                SectionHeading(title: "各项目标")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 14)], spacing: 14) {
                    ForEach(model.goals, id: \.stringID) { goal in Card { GoalRow(goal: goal) } }
                }
                HStack(alignment: .top, spacing: 16) {
                    Card("一周投入分布") { DailyChart(days: model.stats.objects("days")) }
                    Card("时间去了哪里") { CategoryBreakdown(values: model.stats.objects("category_totals")) }.frame(width: 330)
                }
                Card("现在需要完成") {
                    if visibleTasks.isEmpty { EmptyNote(text: "眼下没有需要处理的周期任务。留出空间，继续投入。") }
                    ForEach(visibleTasks, id: \.stringID) { task in TaskRow(task: task) }
                    if !overdueTasks.isEmpty {
                        DisclosureGroup("\(overdueTasks.count) 项逾期任务") {
                            VStack(spacing: 12) { ForEach(overdueTasks, id: \.stringID) { task in TaskRow(task: task) } }.padding(.top, 12)
                        }.foregroundStyle(.secondary)
                    }
                }
                if !model.snapshot.objects("trends").isEmpty {
                    Card("近几周的投入") { TrendChart(values: model.snapshot.objects("trends"), focus: model.categoryName("research")) }
                }
                Color.clear.frame(height: 1).id("end")
            }.padding(28)
        }
        .scrollTo(onAppear: ProcessInfo.processInfo.environment["PERSONAL_OS_SMOKE_SCROLL"])
    }
}

extension View {
    // Development instrumentation, like PERSONAL_OS_SMOKE_PAGE: scroll to the page end for screenshots.
    @ViewBuilder func scrollTo(onAppear anchor: String?) -> some View {
        if anchor == "end" {
            ScrollViewReader { proxy in
                self.onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { proxy.scrollTo("end", anchor: .bottom) } }
            }
        } else {
            self
        }
    }
}

private func shortDate(_ day: String) -> String {
    let parts = day.split(separator: "-")
    return parts.count == 3 ? "\(Int(parts[1]) ?? 0)/\(Int(parts[2]) ?? 0)" : day
}
private func weekdayName(_ day: String) -> String {
    let names = [String(localized: "周日"), String(localized: "周一"), String(localized: "周二"), String(localized: "周三"), String(localized: "周四"), String(localized: "周五"), String(localized: "周六")]
    return names[Calendar(identifier: .gregorian).component(.weekday, from: parsedDate(day)) - 1]
}

// Stacked by category so a day shows what the hours went to, not only how many.
struct DailyChart: View {
    @EnvironmentObject var model: AppModel
    let days: [JSON]
    // PERSONAL_OS_SMOKE_HOVER=M/D shows that day's hover card, for screenshots.
    @State private var hovered: String? = ProcessInfo.processInfo.environment["PERSONAL_OS_SMOKE_HOVER"]
    struct Segment: Identifiable { let id: String; let date: String; let name: String; let hours: Double }
    var segments: [Segment] {
        // Dictionary order is random; stack in category order so colours sit the same way every day.
        let order = categoryIDs
        return days.flatMap { day -> [Segment] in
            let values = day["by_category"] as? JSON ?? [:]
            return order.compactMap { key in
                let seconds = (values[key] as? NSNumber)?.doubleValue ?? 0
                return seconds > 0 ? Segment(id: day.string("day") + key, date: shortDate(day.string("day")),
                                             name: model.categoryName(key), hours: seconds / 3600) : nil
            }
        }
    }
    // Profile order first, then any historical category that is no longer configured.
    var categoryIDs: [String] {
        let used = Set(days.flatMap { ($0["by_category"] as? JSON ?? [:]).keys })
        let configured = model.categories.map { $0.string("id") }
        return configured.filter(used.contains) + used.subtracting(configured).sorted()
    }
    var body: some View {
        let weekdays = Dictionary(uniqueKeysWithValues: days.map { (shortDate($0.string("day")), weekdayName($0.string("day"))) })
        Chart(segments) { segment in
            BarMark(x: .value("日期", segment.date), y: .value("小时", segment.hours), width: .ratio(0.5))
                .foregroundStyle(by: .value("类别", segment.name)).cornerRadius(3)
                .opacity(hovered == nil || hovered == segment.date ? 1 : 0.4)
        }
        .chartXScale(domain: days.map { shortDate($0.string("day")) })
        .chartForegroundStyleScale(domain: categoryIDs.map(model.categoryName), range: categoryIDs.map(categoryColor))
        .chartXAxis {
            AxisMarks { value in
                AxisValueLabel {
                    if let date = value.as(String.self) {
                        VStack(spacing: 2) { Text(weekdays[date] ?? ""); Text(date).foregroundStyle(Theme.muted) }.font(.caption2)
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine().foregroundStyle(Theme.hairline)
                AxisValueLabel { if let hours = value.as(Double.self) { Text(String(format: "%gh", hours)).font(.caption2) } }
            }
        }
        .chartLegend(position: .bottom, alignment: .leading, spacing: 14)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                let plot = geometry[proxy.plotAreaFrame]
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        if case .active(let location) = phase, !segments.isEmpty {
                            hovered = proxy.value(atX: location.x - plot.minX, as: String.self)
                        } else {
                            hovered = nil
                        }
                    }
                if let date = hovered, let day = days.first(where: { shortDate($0.string("day")) == date }), let x = proxy.position(forX: date) {
                    // Beside the bar (right, or left near the edge) so the card never covers it.
                    let half = plot.width / CGFloat(max(days.count, 1)) / 4 + 8
                    let right = plot.minX + x + half
                    DayTooltip(title: (weekdays[date] ?? "") + " " + date, day: day, order: categoryIDs)
                        .offset(x: right + DayTooltip.width <= geometry.size.width ? right : max(0, plot.minX + x - half - DayTooltip.width), y: plot.minY)
                        .allowsHitTesting(false)
                }
            }
        }
        .overlay { if segments.isEmpty { Text("这一周还没有保存的投入").font(.callout).foregroundStyle(Theme.muted) } }
        .frame(height: 210)
    }
}
// Hover card for one day of the chart: the total and each category's exact time.
private struct DayTooltip: View {
    @EnvironmentObject var model: AppModel
    static let width: CGFloat = 200
    let title: String
    let day: JSON
    let order: [String]
    var body: some View {
        let values = day["by_category"] as? JSON ?? [:]
        let items = order.compactMap { key -> (String, Double)? in
            let seconds = (values[key] as? NSNumber)?.doubleValue ?? 0
            return seconds > 0 ? (key, seconds) : nil
        }
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title).font(.caption.weight(.semibold))
                Spacer()
                Text(duration(items.reduce(0) { $0 + $1.1 })).font(.caption.weight(.semibold)).monospacedDigit()
            }
            if items.isEmpty { Text("这一天没有保存的投入").font(.caption2).foregroundStyle(Theme.muted) }
            ForEach(items, id: \.0) { item in
                HStack(spacing: 6) {
                    Circle().fill(categoryColor(item.0)).frame(width: 6, height: 6)
                    Text(model.categoryName(item.0))
                    Spacer()
                    Text(duration(item.1)).monospacedDigit()
                }.font(.caption2)
            }
        }
        .padding(10).frame(width: Self.width, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(Theme.hairline, lineWidth: 1))
        .shadow(color: .black.opacity(0.08), radius: 8, y: 3)
    }
}
struct CategoryBreakdown: View {
    let values: [JSON]
    var total: Double { values.reduce(0) { $0 + $1.number("seconds") } }
    var sorted: [JSON] { values.sorted { $0.number("seconds") > $1.number("seconds") } }
    var body: some View {
        VStack(spacing: 13) {
            ForEach(sorted, id: \.stringID) { item in
                let seconds = item.number("seconds")
                VStack(spacing: 6) {
                    HStack {
                        Circle().fill(categoryColor(item.string("id"))).frame(width: 7, height: 7)
                        Text(item.string("name")).foregroundStyle(seconds > 0 ? Theme.ink : Theme.muted)
                        Spacer()
                        if seconds > 0 && total > 0 { Text("\(Int((seconds / total * 100).rounded()))%").foregroundStyle(Theme.muted).monospacedDigit() }
                        Text(duration(seconds)).foregroundStyle(seconds > 0 ? Theme.ink : Theme.muted).monospacedDigit().frame(minWidth: 72, alignment: .trailing)
                    }.font(.caption)
                    MeterBar(value: total > 0 ? seconds / total : 0, color: categoryColor(item.string("id")), height: 4)
                }
            }
        }
    }
}
struct TrendChart: View {
    let values: [JSON]
    var focus = ""
    let total = String(localized: "总工作")
    struct Point: Identifiable { let id: String; let week: String; let series: String; let hours: Double }
    var points: [Point] {
        values.flatMap { week -> [Point] in
            let label = String(localized: "\(shortDate(week.string("week_start"))) 起")
            return [Point(id: label + "w", week: label, series: total, hours: week.number("work_seconds") / 3600),
                    Point(id: label + "r", week: label, series: focus, hours: week.number("research_seconds") / 3600)]
        }
    }
    var body: some View {
        Chart(points) { point in
            LineMark(x: .value("周", point.week), y: .value("小时", point.hours))
                .foregroundStyle(by: .value("系列", point.series)).interpolationMethod(.monotone).lineStyle(StrokeStyle(lineWidth: 2.5))
            // Label only the total; research labels would collide with it on light weeks.
            PointMark(x: .value("周", point.week), y: .value("小时", point.hours)).foregroundStyle(by: .value("系列", point.series))
                .annotation(position: .top, spacing: 6) {
                    if point.series == total { Text(String(format: "%.1fh", point.hours)).font(.caption2).foregroundStyle(Theme.muted) }
                }
        }
        .chartForegroundStyleScale([total: Theme.muted, focus: Theme.category("research")])
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine().foregroundStyle(Theme.hairline)
                AxisValueLabel { if let hours = value.as(Double.self) { Text(String(format: "%gh", hours)).font(.caption2) } }
            }
        }
        .chartLegend(position: .bottom, alignment: .leading)
        .frame(height: 190)
    }
}

struct TimePage: View {
    @EnvironmentObject var model: AppModel
    @State private var selectedCategory = "research"
    @State private var showAdd = false
    @State private var showDiscard = false
    @State private var pendingDeletion: JSON?
    var savedActivities: [JSON] { model.snapshot.objects("activities").filter { $0.flag("saved", true) } }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(title: "记录投入，保持连续", subtitle: "和菜单栏计时器是同一份记录。旧记录只有每天的总时长，所以按天显示。")
                Card {
                    HStack(alignment: .center, spacing: 22) {
                        VStack(alignment: .leading, spacing: 8) {
                            Label(model.timer.flag("active") ? model.categoryName(model.timer.string("category")) : String(localized: "准备开始"), systemImage: "timer").foregroundStyle(.secondary)
                            Text(clockDuration(model.liveElapsed)).font(Theme.number(48, weight: .medium)).monospacedDigit().foregroundStyle(Theme.ink)
                            Text(model.timer.flag("running") ? "正在记录 · 尚未保存" : model.timer.flag("active") ? "已暂停" : "选择一个类别，开始投入").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        VStack(alignment: .leading, spacing: 12) {
                            // While timing, choosing another category switches at once: the current
                            // segment is saved and the new category starts from zero.
                            Picker("活动类别", selection: Binding(get: { selectedCategory }, set: { value in
                                selectedCategory = value
                                if model.timer.flag("active") && value != model.timer.string("category") { model.timerCommand("switch", category: value) }
                            })) {
                                ForEach(model.activeCategories, id: \.stringID) { item in Text(item.string("name")).tag(item.string("id")) }
                            }.frame(width: 250)
                            HStack {
                                if !model.timer.flag("active") {
                                    Button("开始计时") { model.timerCommand("start", category: selectedCategory) }.buttonStyle(.borderedProminent)
                                } else {
                                    Button(model.timer.flag("running") ? "暂停" : "继续") { model.timerCommand(model.timer.flag("running") ? "pause" : "resume") }
                                    Button("保存并结束") { model.timerCommand("stop") }.buttonStyle(.borderedProminent)
                                }
                            }
                        }
                    }
                    HStack {
                        Text("换类别会先保存当前这段，新类别从零开始计时。").font(.caption2).foregroundStyle(.secondary)
                        Spacer()
                        Button("找回刚丢弃的计时") { model.timerCommand("restore") }.font(.caption)
                        if model.timer.flag("active") { Button("丢弃本次", role: .destructive) { showDiscard = true }.font(.caption) }
                    }
                }
                Card("每日时间分布") { DailyChart(days: model.stats.objects("days")) }
                Card {
                    HStack { Text("已保存记录").font(.headline); Spacer(); Button { showAdd = true } label: { Label("补记时间", systemImage: "plus") } }
                    if savedActivities.isEmpty { EmptyNote(text: "这一周还没有保存记录。完成计时或补记一段投入后，它会显示在这里。") }
                    ForEach(savedActivities, id: \.stringID) { activity in
                        ActivityRow(activity: activity) { pendingDeletion = activity }
                        Divider()
                    }
                }
            }.padding(28)
        }
        .onAppear { selectedCategory = model.timer.string("category", "research") }
        .onAppear(perform: syncCategory)
        .onChange(of: model.timer.string("category")) { _ in syncCategory() }
        .sheet(isPresented: $showAdd) { ManualActivityEditor().environmentObject(model) }
        .confirmationDialog("丢弃当前计时？之后仍可找回。", isPresented: $showDiscard) { Button("丢弃本次", role: .destructive) { model.timerCommand("discard") } }
        .confirmationDialog("删除这条记录？", isPresented: Binding(get: { pendingDeletion != nil }, set: { if !$0 { pendingDeletion = nil } }), presenting: pendingDeletion) { activity in
            Button("删除", role: .destructive) { model.send(["action": "delete_activity", "id": activity.string("id")], message: String(localized: "记录已删除")) }
        } message: { activity in
            Text("\(model.categoryName(activity.string("category"))) · \(activity.string("day")) · \(activityTime(activity)) · \(duration(activity.number("seconds")))")
        }
    }
    // The picker follows the category being timed (or last used) rather than a fixed default.
    private func syncCategory() {
        let current = model.timer.string("category")
        if model.activeCategories.contains(where: { $0.string("id") == current }) { selectedCategory = current }
    }
}

// One saved record: clock range when the timer recorded it, click (or right-click) to delete.
struct ActivityRow: View {
    @EnvironmentObject var model: AppModel
    let activity: JSON
    let delete: () -> Void
    @State private var hovering = false
    private var deletable: Bool { activity.string("source") != "legacy_log" }
    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3).fill(categoryColor(activity.string("category"))).frame(width: 4, height: 30)
            VStack(alignment: .leading, spacing: 3) { Text(model.categoryName(activity.string("category"))).font(.subheadline.weight(.medium)); Text(activity.string("day")).font(.caption).foregroundStyle(.secondary) }
            Spacer()
            Text(activityTime(activity)).font(.caption).foregroundStyle(.secondary).monospacedDigit()
            Text(duration(activity.number("seconds"))).monospacedDigit().frame(width: 115, alignment: .trailing)
        }
        .padding(.vertical, 6).padding(.horizontal, 8)
        .background(hovering && deletable ? Theme.accent.opacity(0.06) : Color.clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .onTapGesture { if deletable { delete() } }
        .contextMenu { if deletable { Button("删除这条记录", role: .destructive, action: delete) } }
        .help(deletable ? "点击可删除这条记录" : "旧日志里的记录不能在应用里删除")
    }
}
func activityTime(_ activity: JSON) -> String {
    if !activity.string("start_time").isEmpty { return activity.string("start_time") + "–" + activity.string("end_time") }
    switch activity.string("source") {
    case "manual": return String(localized: "手工补记")
    case "legacy_log": return activity.string("logged_time").isEmpty ? String(localized: "旧日志 · 只有时长") : String(localized: "记录于 \(activity.string("logged_time"))")
    default: return String(localized: "只有当天总时长")
    }
}

struct ManualActivityEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()
    @State private var category = "reading"
    @State private var minutes = "30"
    @State private var goalIDs: Set<String> = []
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("补记一段投入").font(.title2.bold())
            Form {
                DatePicker("日期", selection: $date, displayedComponents: .date)
                Picker("类别", selection: $category) { ForEach(model.activeCategories, id: \.stringID) { c in Text(c.string("name")).tag(c.string("id")) } }
                TextField("时长（分钟）", text: $minutes)
                DisclosureGroup("关联更多目标（可选）") {
                    ForEach(model.profile.objects("goals"), id: \.stringID) { goal in
                        Toggle(goal.string("name"), isOn: Binding(get: { goalIDs.contains(goal.string("id")) }, set: { if $0 { goalIDs.insert(goal.string("id")) } else { goalIDs.remove(goal.string("id")) } }))
                    }
                }
            }.formStyle(.grouped)
            Text("同一段时间只属于一个类别；关联多个目标不会增加总投入。").font(.caption).foregroundStyle(.secondary)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存补记") {
                guard let seconds = validatedSeconds(minutes, unit: 60, maximum: 1440), seconds > 0 else { return }
                model.send(["action": "add_activity", "day": localDate(date), "category": category, "seconds": seconds, "goal_ids": Array(goalIDs)], message: String(localized: "时间已补记"), completion: { dismiss() })
            }.buttonStyle(.borderedProminent).disabled((validatedSeconds(minutes, unit: 60, maximum: 1440) ?? 0) < 1 || model.loading) }
        }.padding(24).frame(width: 480, height: 470)
        .onAppear { if !model.activeCategories.contains(where: { $0.string("id") == category }) { category = model.activeCategories.first?.string("id") ?? "" } }
    }
}

struct TaskRow: View {
    @EnvironmentObject var model: AppModel
    let task: JSON
    @State private var editing = false
    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: task.string("status") == "completed" ? "checkmark.circle.fill" : task.string("status") == "skipped" ? "minus.circle" : "circle")
                .foregroundStyle(task.string("status") == "completed" ? .teal : task.flag("is_overdue") ? .orange : .secondary)
            VStack(alignment: .leading, spacing: 4) {
                Text(task.string("name")).font(.subheadline.weight(.medium))
                Text("\(task.string("period_key")) · \(task.string("visible_from")) 开始提醒 · \(task.string("due_on")) 截止").font(.caption2).foregroundStyle(.secondary)
                if !task.string("review_text").isEmpty { Text(task.string("review_text")).lineLimit(2).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
            if task.flag("is_overdue") && task.string("status") == "pending" { Text("逾期").font(.caption).foregroundStyle(.orange) }
            if !task.flag("is_visible") && task.string("status") == "pending" { Text("未到提醒时间").font(.caption).foregroundStyle(.secondary) }
            Button("记录复盘") { editing = true }.font(.caption)
            if task.string("status") == "pending" {
                Button("完成") { model.send(["action": "complete_task", "id": task.string("id"), "status": "completed", "text": task.string("review_text")], message: String(localized: "已完成本期任务")) }.font(.caption)
            }
        }.padding(.vertical, 5)
        .sheet(isPresented: $editing) { TaskReviewEditor(task: task).environmentObject(model) }
    }
}
struct TaskReviewEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let task: JSON
    @State private var text = ""
    @State private var status = "pending"
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(task.string("name")).font(.title2.bold())
            Text("\(task.string("period_key")) · 截止 \(task.string("due_on"))").foregroundStyle(.secondary)
            if !task.string("description").isEmpty { Text(task.string("description")).font(.callout) }
            TextEditor(text: $text).font(.body).padding(8).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8)).overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary)).accessibilityLabel("本期复盘内容")
            Picker("本期状态", selection: $status) { Text("待完成").tag("pending"); Text("已完成").tag("completed"); Text("跳过").tag("skipped") }.pickerStyle(.segmented)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存本期记录") { model.send(["action": "complete_task", "id": task.string("id"), "status": status, "text": text], message: String(localized: "本期记录已保存"), completion: { dismiss() }) }.buttonStyle(.borderedProminent).disabled(model.loading) }
        }.padding(24).frame(width: 590, height: 470)
        .onAppear { text = task.string("review_text"); status = task.string("status", "pending") }
    }
}

struct ReviewPage: View {
    @EnvironmentObject var model: AppModel
    @State private var tab = "weekly"
    @State private var text = ""
    @State private var dirty = false
    @State private var loadedWeek = ""
    @State private var historyFilter = "all"
    var weekReview: JSON { model.snapshot.objects("reviews").first { $0.string("week_start") == model.currentWeek } ?? [:] }
    var filteredTasks: [JSON] { model.tasks.filter { historyFilter == "all" || (historyFilter == "pending" ? $0.string("status") == "pending" : $0.string("status") != "pending") } }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(title: "留一点时间，看看方向", subtitle: "保留每一期的完成记录和判断，让下一周的投入更有依据。")
                Picker("复盘内容", selection: $tab) { Text("周度复盘").tag("weekly"); Text("周期任务与历史").tag("tasks") }.pickerStyle(.segmented).frame(maxWidth: 400)
                if tab == "weekly" {
                    Card {
                        HStack { Text("\(model.currentWeek) 这一周").font(.headline); Spacer(); if weekReview.flag("completed") { Label("已完成", systemImage: "checkmark.circle.fill").font(.caption).foregroundStyle(.teal) }; if dirty { Text("有未保存修改").font(.caption).foregroundStyle(.orange) } }
                        HStack(spacing: 26) { Text("工作 \(duration(reviewStats.number("work_seconds")))"); Text("\(model.categoryName("research")) \(duration(reviewStats.number("research_seconds")))"); Text("\(model.categoryName("reading"))有效日 \(Int(reviewStats.number("reading_days")))") }.font(.subheadline)
                        if weekReview.flag("completed") { Text("上面的数字定格在完成复盘那天。").font(.caption).foregroundStyle(.secondary) }
                        Text("本周做成了什么？投入与预期哪里有差距？下周准备做什么调整？").font(.callout).foregroundStyle(.secondary)
                        TextEditor(text: Binding(get: { text }, set: { text = $0; dirty = true })).font(.body).padding(10).frame(minHeight: 250).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 9)).overlay(RoundedRectangle(cornerRadius: 9).stroke(.quaternary)).accessibilityLabel("周度复盘正文")
                        if dirty && loadedWeek != model.currentWeek {
                            HStack { Text("未保存内容来自 \(loadedWeek) 这一周。").font(.caption).foregroundStyle(.orange); Button("返回编辑周") { model.selectedWeek = loadedWeek; model.refresh() } }
                        }
                        HStack {
                            if dirty { Button("放弃未保存修改") { loadReview(force: true) } }
                            Spacer()
                            Button("保存草稿") { save(completed: false) }.disabled(model.loading)
                            Button("完成周复盘") { save(completed: true) }.buttonStyle(.borderedProminent).disabled(model.loading)
                        }
                    }
                    Card("各项目标") { ForEach(reviewStats.objects("goals"), id: \.stringID) { goal in GoalRow(goal: goal); Divider() } }
                    Card("已有周复盘") {
                        if model.snapshot.objects("reviews").isEmpty { EmptyNote(text: "保存第一篇周复盘后，会在这里形成历史。") }
                        ForEach(model.snapshot.objects("reviews"), id: \.stringID) { review in
                            HStack { Text(review.string("week_start")); Text(review.flag("completed") ? "已完成" : "草稿").font(.caption).foregroundStyle(.secondary); Spacer(); Text(String(review.string("text").prefix(45))).font(.caption).foregroundStyle(.secondary).lineLimit(1); Button("查看") { model.selectedWeek = review.string("week_start"); model.refresh() }.disabled(dirty) }
                        }
                    }
                } else {
                    Card {
                        HStack { Text("所有周期任务").font(.headline); Spacer(); Picker("筛选", selection: $historyFilter) { Text("全部").tag("all"); Text("待完成").tag("pending"); Text("完成与跳过").tag("done") }.frame(width: 170) }
                        Text("包括还没到提醒时间的任务和以往各期的记录。").font(.caption).foregroundStyle(.secondary)
                        if filteredTasks.isEmpty { EmptyNote(text: "当前筛选没有任务。可以在设置中添加周期任务。") }
                        ForEach(filteredTasks, id: \.stringID) { task in TaskRow(task: task); Divider() }
                    }
                }
            }.padding(28)
        }
        .onAppear { loadReview(force: true) }
        .onChange(of: model.currentWeek) { _ in loadReview(force: false) }
        .onChange(of: model.snapshot.objects("reviews").count) { _ in if !dirty { loadReview(force: true) } }
    }
    var reviewStats: JSON { weekReview.flag("completed") ? weekReview.object("statistics") : model.stats }
    private func loadReview(force: Bool) {
        if dirty && !force { return }
        loadedWeek = ""; text = weekReview.string("text"); loadedWeek = model.currentWeek; dirty = false
    }
    private func save(completed: Bool) {
        guard loadedWeek == model.currentWeek else { model.error = String(localized: "复盘周已切换。请先回到原周保存修改，或放弃修改后再加载当前周。"); return }
        model.send(["action": "save_review", "week_start": loadedWeek, "text": text, "completed": completed], message: completed ? String(localized: "周复盘已完成") : String(localized: "草稿已保存"), completion: { dirty = false })
    }
}

struct EditorTarget: Identifiable {
    let id = UUID()
    let kind: String
    let item: JSON
}
struct SettingsPage: View {
    @EnvironmentObject var model: AppModel
    @State private var editor: EditorTarget?
    @State private var appLanguage = AppLanguage.selected
    @AppStorage("dailySplashEnabled") private var splashEnabled = true
    @AppStorage("showMenuBarTimer") private var showMenuBarTimer = false
    private var profileSummary: String {
        let trial = model.profile.object("trial")
        var parts = [model.profile.string("timezone"), String(localized: "周一开始")]
        if trial["weeks"] != nil { parts.append(String(localized: "\(Int(trial.number("weeks"))) 周试运行")) }
        return parts.joined(separator: " · ")
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                PageHeading(title: "适合你的投入方式", subtitle: "类别、达标标准和周期任务都可以随时调整。")
                Card {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) { Text(model.profile.string("name", String(localized: "个人配置"))).font(.headline); Text(profileSummary).font(.caption).foregroundStyle(.secondary) }
                        Spacer(); Button("编辑基本设置") { editor = EditorTarget(kind: "general", item: model.profile) }
                    }
                    Text("勾选「计入工作」的类别会算进总工作投入。").font(.caption).foregroundStyle(.secondary)
                }
                Card {
                    HStack { Text("时间类别").font(.headline); Spacer(); Button { editor = EditorTarget(kind: "category", item: [:]) } label: { Label("添加类别", systemImage: "plus") } }
                    ForEach(model.categories, id: \.stringID) { category in
                        HStack {
                            Circle().fill(categoryColor(category.string("id"))).frame(width: 9, height: 9)
                            Text(category.string("name"))
                            Text(category.string("bar_label")).font(.caption).foregroundStyle(.secondary).help("状态栏显示的名称")
                            if category.flag("archived") { Text("已归档").font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            Text(category.flag("counts_as_work") ? "计入工作" : "不计入工作").font(.caption).foregroundStyle(.secondary)
                            Button("编辑") { editor = EditorTarget(kind: "category", item: category) }
                        }.padding(.vertical, 4)
                    }
                }
                Card {
                    HStack { Text("每周投入目标").font(.headline); Spacer(); Button { editor = EditorTarget(kind: "goal", item: [:]) } label: { Label("添加目标", systemImage: "plus") } }
                    ForEach(model.profile.objects("goals"), id: \.stringID) { goal in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) { Text(goal.string("name")); Text(goalSummary(goal)).font(.caption).foregroundStyle(.secondary) }
                            Spacer(); Button("编辑") { editor = EditorTarget(kind: "goal", item: goal) }
                        }.padding(.vertical, 5)
                    }
                }
                Card {
                    HStack { Text("周期任务").font(.headline); Spacer(); Button { editor = EditorTarget(kind: "task", item: [:]) } label: { Label("添加任务", systemImage: "plus") } }
                    ForEach(model.profile.objects("task_templates"), id: \.stringID) { task in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(task.string("name"))
                                (Text("\(recurrenceName(task.object("recurrence").string("kind"))) · 截止前 \(Int(task.object("visibility").number("days", 1))) 天开始提醒") + Text(task.flag("enabled", true) ? "" : " · 已停用")).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer(); Button("编辑") { editor = EditorTarget(kind: "task", item: task) }
                        }.padding(.vertical, 5)
                    }
                    Text("修改只影响以后各期，已有记录不变。").font(.caption2).foregroundStyle(.tertiary)
                }
                Card("界面语言") {
                    Picker("界面语言", selection: $appLanguage) {
                        Text("跟随系统").tag(AppLanguage.system)
                        Text(verbatim: "简体中文").tag(AppLanguage.chinese) // l10n: keep
                        Text(verbatim: "English").tag(AppLanguage.english)
                    }.labelsHidden().pickerStyle(.segmented)
                        .onChange(of: appLanguage) { $0.save() }
                        .accessibilityLabel("界面语言")
                    Text("重新打开 Personal OS 后生效。").font(.caption).foregroundStyle(Theme.muted)
                }
                Card("菜单栏") {
                    Toggle("在菜单栏显示计时器", isOn: $showMenuBarTimer)
                    Text("在屏幕顶部的菜单栏里开始、暂停或切换计时。").font(.caption).foregroundStyle(Theme.muted)
                }
                Card("每日彩蛋") {
                    Toggle("每天第一次打开时，先看一幅名画和一句诗词", isOn: $splashEnabled)
                    HStack {
                        Text("画作来自大都会艺术博物馆开放获取（CC0 公有领域）；诗词应季轮换，农历节日另有诗句。").font(.caption).foregroundStyle(Theme.muted)
                        Spacer()
                        Button("看看今天的") { model.showingSplash = true }.disabled(model.inspiration == nil)
                    }
                }
                Card("本地数据") {
                    Text("计时记录位置：\(model.snapshot.object("source").string("path", String(localized: "尚未读取")))").font(.caption).textSelection(.enabled).foregroundStyle(.secondary)
                    ForEach(Array((model.snapshot.object("source")["warnings"] as? [String] ?? []).enumerated()), id: \.offset) { _, warning in Label(warning, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary) }
                    HStack { Button("导出完整备份…") { model.exportBackup() }; Button("导入备份…") { model.importBackup() } }
                }
            }.padding(28)
        }
        .sheet(item: $editor) { target in
            Group {
                switch target.kind {
                case "category": CategoryEditor(item: target.item)
                case "goal": GoalEditor(item: target.item)
                case "task": TaskTemplateEditor(item: target.item)
                default: GeneralSettingsEditor()
                }
            }.environmentObject(model)
        }
    }
    private func goalSummary(_ goal: JSON) -> String {
        switch goal.string("kind") {
        case "frequency": return String(localized: "每周 ≥\(Int(goal.number("minimum_distinct_days"))) 天，各日累计 ≥\(Int(goal.number("minimum_daily_seconds") / 60)) 分钟")
        case "minimum_duration": return String(localized: "每周至少 \(duration(goal.number("minimum_seconds")))")
        case "maximum_duration": return String(localized: "每周不超过 \(duration(goal.number("maximum_seconds")))")
        case "duration_range": return String(localized: "每周 \(compactDuration(goal.number("minimum_seconds")))–\(compactDuration(goal.number("maximum_seconds")))")
        default: return String(localized: "仅观察，不判定达标")
        }
    }
}
func recurrenceName(_ kind: String) -> String {
    ["weekly": String(localized: "每周"), "monthly": String(localized: "每月"), "quarterly": String(localized: "每季度"), "yearly": String(localized: "每年")][kind] ?? kind
}

struct CategoryEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let item: JSON
    @State private var name = ""
    @State private var barLabel = ""
    @State private var work = false
    @State private var archived = false
    // Mirrors domain.BAR_LABEL_PATTERN: SketchyBar shows a single English word.
    private var barLabelValid: Bool { barLabel.range(of: "^[A-Za-z][A-Za-z0-9]{0,15}$", options: .regularExpression) != nil }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(item.isEmpty ? "添加类别" : "编辑类别").font(.title2.bold())
            Form {
                TextField("类别名称", text: $name)
                TextField("状态栏名称（一个英文单词）", text: $barLabel)
                Toggle("计入总工作时间", isOn: $work)
                Toggle("归档（历史记录仍保留）", isOn: $archived)
            }.formStyle(.grouped)
            Text("状态栏只显示英文名，例如 Reading。类别使用稳定编号，改名不会改变过去记录的归属。").font(.caption).foregroundStyle(.secondary)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存类别") {
                var value = item
                value["id"] = item.string("id", "category-" + UUID().uuidString.lowercased().prefix(8))
                value["name"] = name.trimmingCharacters(in: .whitespacesAndNewlines)
                value["bar_label"] = barLabel
                value["counts_as_work"] = work; value["archived"] = archived
                model.replaceProfileItem("categories", item: value, completion: { dismiss() })
            }.buttonStyle(.borderedProminent).disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !barLabelValid || model.loading) }
        }.padding(24).frame(width: 470, height: 380)
        .onAppear { name = item.string("name"); barLabel = item.string("bar_label"); work = item.flag("counts_as_work"); archived = item.flag("archived") }
    }
}

struct GoalEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let item: JSON
    @State private var name = ""
    @State private var kind = "frequency"
    @State private var strength = "flexible"
    @State private var scope = "category"
    @State private var selected: Set<String> = ["reading"]
    @State private var minimumHours = "1"
    @State private var maximumHours = "5"
    @State private var days = 3
    @State private var dailyMinutes = "30"
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(item.isEmpty ? "添加每周目标" : "编辑每周目标").font(.title2.bold())
            Form {
                Section {
                    TextField("目标名称", text: $name)
                    Picker("目标类型", selection: $kind) {
                        Text("最低投入时间").tag("minimum_duration"); Text("最高投入时间").tag("maximum_duration")
                        Text("建议投入范围").tag("duration_range"); Text("有效投入天数").tag("frequency"); Text("仅观察").tag("observe")
                    }
                    Picker("约束强度", selection: $strength) { Text("硬性").tag("hard"); Text("弹性").tag("flexible"); Text("仅观察").tag("observe") }
                }
                Section("统计范围") {
                    Picker("范围", selection: $scope) { Text("指定类别").tag("category"); Text("所有计入工作的类别").tag("work") }
                    if scope == "category" {
                        ForEach(model.categories, id: \.stringID) { category in
                            Toggle(category.string("name"), isOn: Binding(get: { selected.contains(category.string("id")) }, set: { if $0 { selected.insert(category.string("id")) } else { selected.remove(category.string("id")) } }))
                        }
                    }
                }
                Section("达标标准") {
                    if kind == "frequency" {
                        Stepper("至少 \(days) 个不同日期", value: $days, in: 1...7)
                        TextField("各日累计至少（分钟）", text: $dailyMinutes)
                        Text("同日可以分多次累计，一天超额投入仍只计一个有效日。").font(.caption).foregroundStyle(.secondary)
                    } else if kind != "observe" {
                        if kind != "maximum_duration" { TextField("每周最低（小时）", text: $minimumHours) }
                        if kind != "minimum_duration" { TextField("每周最高（小时）", text: $maximumHours) }
                        if kind == "duration_range" { Text("最低须大于 0；只想设上限请选「最高投入时间」。").font(.caption).foregroundStyle(.secondary) }
                    } else { Text("只展示投入，不计算成功或失败。").font(.caption).foregroundStyle(.secondary) }
                }
            }.formStyle(.grouped)
            Text("修改立即生效；已完成的周复盘仍按当时的目标和数字。").font(.caption).foregroundStyle(.secondary)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存目标") { save() }.buttonStyle(.borderedProminent).disabled(!valid || model.loading) }
        }.padding(24).frame(width: 560, height: 650)
        .onAppear {
            name = item.string("name"); kind = item.string("kind", "frequency"); strength = item.string("strength", "flexible")
            let filter = item.object("filter"); scope = filter.flag("counts_as_work") ? "work" : "category"
            if !item.isEmpty { selected = Set(filter["category_ids"] as? [String] ?? []) }
            minimumHours = String(format: "%g", item.number("minimum_seconds", 3600) / 3600)
            maximumHours = String(format: "%g", item.number("maximum_seconds", 18000) / 3600)
            days = Int(item.number("minimum_distinct_days", 3)); dailyMinutes = String(format: "%g", item.number("minimum_daily_seconds", 1800) / 60)
        }
    }
    var valid: Bool {
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (scope == "category" && selected.isEmpty) { return false }
        if kind == "frequency" { return (validatedSeconds(dailyMinutes, unit: 60, maximum: 1440) ?? 0) > 0 }
        if kind == "minimum_duration" { return (validatedSeconds(minimumHours, unit: 3600, maximum: 168) ?? 0) > 0 }
        if kind == "maximum_duration" { return (validatedSeconds(maximumHours, unit: 3600, maximum: 168) ?? 0) > 0 }
        if kind == "duration_range" {
            // The backend requires a positive lower bound; a 0 lower bound is a 最高投入时间 goal.
            guard let minimum = validatedSeconds(minimumHours, unit: 3600, maximum: 168),
                  let maximum = validatedSeconds(maximumHours, unit: 3600, maximum: 168) else { return false }
            return maximum >= minimum
        }
        return true
    }
    private func save() {
        guard valid else { return }
        var value = item
        for key in ["minimum_seconds", "maximum_seconds", "minimum_distinct_days", "minimum_daily_seconds"] { value.removeValue(forKey: key) }
        value["id"] = item.string("id", "goal-" + UUID().uuidString.lowercased().prefix(8)); value["name"] = name.trimmingCharacters(in: .whitespacesAndNewlines)
        value["kind"] = kind; value["period"] = "week"; value["strength"] = kind == "observe" ? "observe" : strength
        value["filter"] = scope == "work" ? ["counts_as_work": true] : ["category_ids": Array(selected).sorted()]
        if kind == "frequency" { value["minimum_distinct_days"] = days; value["minimum_daily_seconds"] = validatedSeconds(dailyMinutes, unit: 60, maximum: 1440); value["daily_aggregation"] = "sum"; value["day_boundary"] = "local_midnight" }
        if kind == "minimum_duration" || kind == "duration_range" { value["minimum_seconds"] = validatedSeconds(minimumHours, unit: 3600, maximum: 168) }
        if kind == "maximum_duration" || kind == "duration_range" { value["maximum_seconds"] = validatedSeconds(maximumHours, unit: 3600, maximum: 168) }
        model.replaceProfileItem("goals", item: value, completion: { dismiss() })
    }
}

struct TaskTemplateEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let item: JSON
    @State private var name = ""
    @State private var details = ""
    @State private var kind = "monthly"
    @State private var weekday = "sunday"
    @State private var monthDay = "last"
    @State private var displayDays = 7
    @State private var enabled = true
    @State private var starts = Date()
    let weekdays = [("monday", String(localized: "周一")), ("tuesday", String(localized: "周二")), ("wednesday", String(localized: "周三")), ("thursday", String(localized: "周四")), ("friday", String(localized: "周五")), ("saturday", String(localized: "周六")), ("sunday", String(localized: "周日"))]
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(item.isEmpty ? "添加周期任务" : "编辑周期任务").font(.title2.bold())
            Form {
                TextField("名称", text: $name)
                TextField("描述", text: $details, axis: .vertical).lineLimit(2...4)
                Toggle("启用此任务", isOn: $enabled)
                Picker("重复周期", selection: $kind) { Text("每周").tag("weekly"); Text("每月").tag("monthly"); Text("每季度").tag("quarterly"); Text("每年").tag("yearly") }
                if kind == "weekly" {
                    Picker("截止日", selection: $weekday) { ForEach(weekdays, id: \.0) { Text($0.1).tag($0.0) } }
                } else if kind == "monthly" {
                    Picker("截止日", selection: $monthDay) {
                        Text("当月最后一天").tag("last")
                        ForEach(1...28, id: \.self) { Text("每月 \($0) 日").tag(String($0)) }
                    }
                } else { Text(kind == "quarterly" ? "每个季度最后一天截止" : "每年最后一天截止").foregroundStyle(.secondary) }
                Stepper("截止前 \(displayDays) 天开始提醒", value: $displayDays, in: 1...366)
                DatePicker("开始日期", selection: $starts, displayedComponents: .date)
            }.formStyle(.grouped)
            Text("到了提醒时间才会出现在待办里，每一期分开记录。").font(.caption).foregroundStyle(.secondary)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存任务") { save() }.buttonStyle(.borderedProminent).disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.loading) }
        }.padding(24).frame(width: 540, height: 550)
        .onAppear {
            name = item.string("name"); details = item.string("description"); kind = item.object("recurrence").string("kind", "monthly")
            weekday = item.object("recurrence").string("weekday", "sunday")
            let day = item.object("recurrence")["day"]; monthDay = day as? String ?? (day as? NSNumber)?.stringValue ?? "last"
            displayDays = Int(item.object("visibility").number("days", 7)); enabled = item.flag("enabled", true)
            starts = parsedDate(item.string("starts_on", model.currentDate))
        }
    }
    private func save() {
        var value = item
        value["id"] = item.string("id", "task-" + UUID().uuidString.lowercased().prefix(8)); value["name"] = name.trimmingCharacters(in: .whitespacesAndNewlines)
        value["description"] = details; value["enabled"] = enabled; value["category"] = item.string("category", "review")
        var recurrence: JSON = ["kind": kind]
        if kind == "weekly" { recurrence["weekday"] = weekday }
        else { recurrence["day"] = kind == "monthly" && monthDay != "last" ? (Int(monthDay) ?? 28) as Any : "last" }
        value["recurrence"] = recurrence
        value["visibility"] = ["kind": "calendar_days_ending_on_due", "days": displayDays]
        value["deadline"] = ["kind": "recurrence_date_end"]
        value["starts_on"] = localDate(starts); value["review_template"] = item.string("review_template", "free_text")
        model.replaceProfileItem("task_templates", item: value, completion: { dismiss() })
    }
}

struct GeneralSettingsEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var timezone = ""
    @State private var trialDate = Date()
    @State private var weeks = 4
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("基本设置").font(.title2.bold())
            Form {
                TextField("配置名称", text: $name)
                TextField("时区", text: $timezone)
                Text("例如 Asia/Shanghai。已有日级历史保留原日期。").font(.caption).foregroundStyle(.secondary)
                DatePicker("试运行开始", selection: $trialDate, displayedComponents: .date)
                Stepper("先试运行 \(weeks) 周", value: $weeks, in: 1...52)
                Text("每周从周一开始").foregroundStyle(.secondary)
            }.formStyle(.grouped)
            HStack { Button("取消") { dismiss() }; Spacer(); Button("保存") {
                var profile = model.profile; profile["name"] = name; profile["timezone"] = timezone
                var trial = profile.object("trial"); trial["weeks"] = weeks; trial["started_on"] = localDate(trialDate); profile["trial"] = trial
                model.saveProfile(profile, completion: { dismiss() })
            }.buttonStyle(.borderedProminent).disabled(name.isEmpty || TimeZone(identifier: timezone) == nil || model.loading) }
        }.padding(24).frame(width: 500, height: 400)
        .onAppear { name = model.profile.string("name"); timezone = model.profile.string("timezone", "Asia/Hong_Kong"); weeks = Int(model.profile.object("trial").number("weeks", 4)); trialDate = parsedDate(model.profile.object("trial").string("started_on", model.currentDate)) }
    }
}
