import SwiftUI

private let beijing = TimeZone(identifier: "Asia/Shanghai")!
private let chinese = Locale(identifier: "zh_CN")
private let clock = Date.VerbatimFormatStyle(format: "\(hour: .twoDigits(clock: .twentyFourHour, hourCycle: .zeroBased)):\(minute: .twoDigits):\(second: .twoDigits)",
                                           locale: chinese, timeZone: beijing, calendar: Calendar(identifier: .gregorian))
private let day = Date.VerbatimFormatStyle(format: "\(year: .defaultDigits)-\(month: .twoDigits)-\(day: .twoDigits)",
                                         locale: chinese, timeZone: beijing, calendar: Calendar(identifier: .gregorian))
private let accent = Color.accentColor
private let canvas = Color(nsColor: .underPageBackgroundColor)
private let surface = Color(nsColor: .controlBackgroundColor)

struct StarApp: App {
    var body: some Scene {
        Window("Star 记录", id: "star-roster") {
            RosterView()
                .frame(minWidth: 600, minHeight: 440)
        }
        .defaultSize(width: 760, height: 640)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}

private enum Tab: String, CaseIterable, Identifiable {
    case timeline = "增减记录"
    case members = "当前名单"
    case project = "项目数据"
    var id: Self { self }
}

@MainActor
private final class RosterModel: ObservableObject {
    @Published var roster: Roster?
    @Published var loading = false
    @Published var error: String?
    @Published var tab = Tab.timeline
    @Published var projectRefreshID = 0
    private let archive = Archive()

    func refresh() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        do {
            roster = try await archive.load()
            error = nil
        } catch {
            if error is CancellationError { return }
            self.error = (error as? RosterError)?.errorDescription ?? "读取归档失败，请检查网络后刷新。"
        }
    }
}

struct RosterView: View {
    @StateObject private var model = RosterModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            banner
            Divider()
            tabs(model.roster)
            Divider()
            if model.tab == .project {
                ProjectDashboard(roster: model.roster, refreshID: model.projectRefreshID)
            } else if let roster = model.roster {
                if let error = model.error {
                    notice(error)
                } else if roster.unavailable > 0 || roster.nonComparable > 0 {
                    notice("\(roster.unavailable) 份快照读取失败，\(roster.nonComparable) 份未取得完整名单。")
                }
                if model.tab == .timeline {
                    timeline(roster)
                } else {
                    members(roster)
                }
                Divider()
                footer(roster)
            } else if let error = model.error {
                ContentUnavailableView(error, systemImage: "exclamationmark.arrow.trianglehead.counterclockwise")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ProgressView("正在读取加密快照…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(canvas)
        .task { await model.refresh() }
    }

    private var banner: some View {
        HStack(spacing: 14) {
            Image(systemName: "star.fill")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(accent)
                .frame(width: 42, height: 42)
                .background(accent.opacity(0.12), in: RoundedRectangle(cornerRadius: 11))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text("Star 记录").font(.system(size: 24, weight: .semibold))
                Link("CHNragdoll / anki-pipeline",
                     destination: URL(string: "https://github.com/CHNragdoll/anki-pipeline")!)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.loading {
                ProgressView().controlSize(.small).accessibilityLabel("正在刷新")
            }
            Button {
                if model.tab == .project { model.projectRefreshID += 1 }
                Task { await model.refresh() }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
            .keyboardShortcut("r", modifiers: .command)
            .disabled(model.loading)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .background(surface)
    }

    private func tabs(_ roster: Roster?) -> some View {
        HStack(spacing: 10) {
            Picker("视图", selection: $model.tab) {
                ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 244)
            Spacer()
            if let roster, model.tab != .project {
                Label("\(roster.members.count) 个 Star", systemImage: "star")
                    .fontWeight(.semibold)
                    .foregroundStyle(.primary)
                let count = model.tab == .timeline ? "\(roster.events.count) 条记录" : "\(roster.snapshots.count) 次采集"
                Text("·").accessibilityHidden(true)
                Text(count)
            } else if model.tab == .project {
                Link("打开网页版", destination: ProjectMetrics.pageURL)
            }
        }
        .font(.subheadline.monospacedDigit())
        .foregroundStyle(.secondary)
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .background(surface)
    }

    private func timeline(_ roster: Roster) -> some View {
        let events = roster.events
        return Group {
            if events.isEmpty {
                ContentUnavailableView("没有已记录的增减", systemImage: "clock",
                                       description: Text("当前名单可在上方查看。"))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(groups(events, date: \.time), id: \.date) { section in
                            dateGroup(section.date, count: section.items.count) {
                                ForEach(section.items) { event in
                                    eventRow(event)
                                    if event.id != section.items.last?.id { rowDivider }
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 16)
                }
                .accessibilityIdentifier("star-timeline")
            }
        }
    }

    private func eventRow(_ event: StarEvent) -> some View {
        let color: Color = event.baseline ? .secondary : (event.added ? .green : .red)
        let action = event.baseline ? "历史加星" : (event.added ? "新增" : "取消")
        let symbol = event.baseline ? "clock" : (event.added ? "plus.circle.fill" : "minus.circle.fill")
        return HStack(spacing: 12) {
            AvatarView(star: event.star)
            VStack(alignment: .leading, spacing: 3) {
                profileLink(event.star)
                if event.exactTime == nil {
                    Text("采集发现 · \(shortTime(event.previousAt, relativeTo: event.detectedAt)) 至 \(event.detectedAt.formatted(clock))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 8)
            Label(action, systemImage: symbol)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(color.opacity(0.12), in: Capsule())
                .fixedSize()
            timeLabel(event.time)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private func members(_ roster: Roster) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                ForEach(groups(roster.members, date: \.starredAt), id: \.date) { section in
                    dateGroup(section.date, count: section.items.count) {
                        ForEach(section.items, id: \.id) { member in
                            HStack(spacing: 12) {
                                AvatarView(star: member)
                                profileLink(member)
                                Spacer(minLength: 8)
                                timeLabel(member.starredAt)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            if member.id != section.items.last?.id { rowDivider }
                        }
                    }
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
        }
        .accessibilityIdentifier("star-members")
    }

    private func profileLink(_ star: Star) -> some View {
        Link(destination: star.profileURL) {
            Text(star.login)
                .lineLimit(1)
                .truncationMode(.middle)
                .font(.system(size: 13, weight: .semibold))
        }
        .help("打开 \(star.login) 的 GitHub 主页")
        .handCursor()
    }

    private func timeLabel(_ date: Date?) -> some View {
        Text(date?.formatted(clock) ?? "—")
            .font(.subheadline.monospacedDigit())
            .foregroundStyle(.secondary)
            .frame(width: 68, alignment: .trailing)
    }

    private var rowDivider: some View {
        Divider().padding(.leading, 56)
    }

    private func dateGroup<Rows: View>(_ date: String, count: Int, @ViewBuilder rows: () -> Rows) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(date).font(.subheadline.weight(.semibold)).monospacedDigit()
                Spacer()
                Text("\(count) 条").font(.caption.monospacedDigit())
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal, 3)
            .accessibilityAddTraits(.isHeader)

            VStack(alignment: .leading, spacing: 0, content: rows)
                .background(surface, in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .strokeBorder(.quaternary, lineWidth: 1)
                        .allowsHitTesting(false)
                }
        }
    }

    private func notice(_ message: String) -> some View {
        Label(message, systemImage: "exclamationmark.circle")
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 24)
            .padding(.vertical, 10)
    }

    private func footer(_ roster: Roster) -> some View {
        HStack {
            if let sample = roster.latest {
                Text("最近采集 \(sample.collectedAt.formatted(day)) \(sample.collectedAt.formatted(clock))")
            }
            Spacer()
            Text("北京时间 · 从晚到早")
        }
        .font(.caption.monospacedDigit())
        .foregroundStyle(.secondary)
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .background(surface)
        .help("名单只在本机内存中解密。")
    }

    private func groups<Item>(_ items: [Item], date: (Item) -> Date?) -> [(date: String, items: [Item])] {
        var sections: [(date: String, items: [Item])] = []
        for item in items {
            let label = date(item)?.formatted(day) ?? "时间未知"
            if sections.last?.date == label {
                sections[sections.count - 1].items.append(item)
            } else {
                sections.append((label, [item]))
            }
        }
        return sections
    }

    private func shortTime(_ date: Date, relativeTo end: Date) -> String {
        let time = date.formatted(clock)
        return date.formatted(day) == end.formatted(day) ? time : "\(date.formatted(day)) \(time)"
    }

}
