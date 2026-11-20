import SwiftUI

private let metricsBeijing = TimeZone(identifier: "Asia/Shanghai")!
private var metricsCalendar: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = metricsBeijing
    return calendar
}

struct ProjectMetrics: Decodable {
    struct Reading: Decodable {
        let count: Int
        let collectedAt: Date
    }
    struct History: Decodable {
        let starsBeijing: [String: Reading]
    }

    let history: History
    let collectedAt: Date

    static let pageURL = URL(string: "https://chnragdoll.github.io/anki-pipeline/")!

    static func isPage(_ url: URL) -> Bool {
        url.scheme == pageURL.scheme && url.host == pageURL.host
            && [pageURL.path, pageURL.path + "/", pageURL.path + "/index.html"].contains(url.path)
    }

    static func load() async throws -> ProjectMetrics {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        let url = pageURL.appendingPathComponent("snapshot.json")
        let session = URLSession(configuration: configuration)
        let (data, response) = try await session.data(for: URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw RosterError.invalidResponse }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(Self.self, from: data)
    }

    struct Run: Decodable, Identifiable {
        let collectedAt: Date
        let stars: Int
        let forks: Int
        var id: Date { collectedAt }
    }

    static func runHistory() async throws -> (runs: [Run], missing: Int) {
        let archive = Archive()
        let paths = try await archive.recordedPaths(["snapshot.json"])["snapshot.json"] ?? []
        let rows = await archive.readBatch(paths) { path in
            try archive.decoder().decode(Run.self, from: await archive.publicRun(path: path))
        }
        return (uniqueRuns(rows), paths.count - rows.count)
    }

    static func uniqueRuns(_ rows: [Run]) -> [Run] {
        Dictionary(rows.map { ($0.collectedAt, $0) }, uniquingKeysWith: { _, last in last })
            .values.sorted { $0.collectedAt > $1.collectedAt }
    }

    static func dayKey(_ date: Date) -> String {
        let parts = metricsCalendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year!, parts.month!, parts.day!)
    }

    static func showTime(_ date: Date) -> String {
        let parts = metricsCalendar.dateComponents([.hour, .minute, .second], from: date)
        return String(format: "%02d:%02d:%02d", parts.hour!, parts.minute!, parts.second!)
    }

    static func fullTime(_ date: Date) -> String { "\(dayKey(date)) \(showTime(date))" }

    func reconciliation(with roster: Roster?) -> [DayReconciliation] {
        let readings = history.starsBeijing
        let first = roster?.snapshots.first
        let originalDay = first.map { Self.dayKey($0.collectedAt) }
        let events = Dictionary(grouping: roster?.events.filter { $0.exactTime != nil || !$0.added } ?? []) {
            Self.dayKey($0.time)
        }
        let snapshots = Dictionary(grouping: roster?.snapshots ?? []) { Self.dayKey($0.collectedAt) }
        return readings.keys.sorted(by: >).map { key in
            let reading = readings[key]!
            let previous = metricsCalendar.date(byAdding: .day, value: -1, to: reading.collectedAt)
                .flatMap { readings[Self.dayKey($0)] }
            let dayEvents = events[key] ?? []
            return DayReconciliation(date: key, before: previous, after: reading, baseline: originalDay == key ? first : nil,
                                     hasRoster: originalDay.map { key >= $0 } ?? false,
                                     samples: snapshots[key] ?? [], additions: dayEvents.filter(\.added),
                                     removals: dayEvents.filter { !$0.added })
        }
    }
}

struct DayReconciliation: Identifiable {
    let date: String
    let before: ProjectMetrics.Reading?
    let after: ProjectMetrics.Reading
    let baseline: Snapshot?
    let hasRoster: Bool
    let samples: [Snapshot]
    let additions: [StarEvent]
    let removals: [StarEvent]
    var id: String { date }
    var net: Int? { before.map { after.count - $0.count } }
    var isToday: Bool { date == ProjectMetrics.dayKey(Date()) }
    var cancellationWindow: String? {
        guard let before, let baseline, before.count == baseline.users?.count,
              additions.contains(where: { $0.baseline && $0.time > before.collectedAt }) else { return nil }
        return "\(ProjectMetrics.fullTime(before.collectedAt)) 至 \(ProjectMetrics.fullTime(baseline.collectedAt))"
    }
    var sampledNet: Int? {
        guard let first = samples.first?.users?.count, let last = samples.last?.users?.count, samples.count > 1 else {
            return nil
        }
        return last - first
    }
}

@MainActor
private final class ReconciliationModel: ObservableObject {
    @Published var metrics: ProjectMetrics?
    @Published var error: String?
    @Published var runsByDay: [String: [ProjectMetrics.Run]] = [:]
    @Published var runMessage: String?

    func load() async {
        async let history = try? ProjectMetrics.runHistory()
        do {
            let latest = try await ProjectMetrics.load()
            guard !Task.isCancelled else { return }
            metrics = latest
            error = nil
        } catch {
            guard !Task.isCancelled else { return }
            self.error = "项目数据读取失败。请点击窗口右上角的「刷新」。"
        }
        let loaded = await history
        guard !Task.isCancelled else { return }
        if let loaded {
            runsByDay = Dictionary(grouping: loaded.runs.reversed()) { ProjectMetrics.dayKey($0.collectedAt) }
            runMessage = loaded.missing > 0 ? "\(loaded.missing) 份 Action 快照读取失败。" : nil
        } else {
            runMessage = "逐次 Action 快照读取失败，可刷新后重试。"
        }
    }
}

struct ReconciliationView: View {
    let roster: Roster?
    let refreshID: Int
    @StateObject private var model = ReconciliationModel()

    var body: some View {
        Group {
            if let metrics = model.metrics {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        Text("Star 日净增核对").font(.title2.weight(.semibold))
                            .accessibilityAddTraits(.isHeader)
                        Text("北京时间 · 模型实测值取相邻两天最后一次公开采样的 Star 总数之差。名单快照可确认加星时间及发现取消的时间范围。")
                            .font(.subheadline).foregroundStyle(.secondary)
                        if let error = model.error {
                            Label(error, systemImage: "exclamationmark.circle").font(.caption)
                        }
                        if roster == nil {
                            Label("加密名单尚未加载，目前只能查看公开采样值。", systemImage: "lock")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        let days = metrics.reconciliation(with: roster)
                        let baselineDay = days.first { $0.baseline != nil }
                        if let baselineDay, let baseline = baselineDay.baseline {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("加密名单从 \(ProjectMetrics.fullTime(baseline.collectedAt)) 起有对照")
                                    .font(.subheadline.weight(.semibold))
                                Text("首份名单已有 \(baseline.users?.count ?? 0) 人。此前保留在首份名单中的加星可按 GitHub 时间追溯，此前的取消无法从该归档还原。")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(Color.accentColor.opacity(0.09), in: RoundedRectangle(cornerRadius: 10))
                        }
                        if let message = model.runMessage {
                            Text(message).font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(days) { day in
                            DayReconciliationRow(day: day, runs: model.runsByDay[day.date] ?? [])
                        }
                    }
                    .frame(maxWidth: 800)
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .center)
                }
            } else if let error = model.error {
                ContentUnavailableView(error, systemImage: "exclamationmark.circle")
            } else {
                ProgressView("正在读取公开采样值…")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: refreshID) { await model.load() }
    }
}

private struct DayReconciliationRow: View {
    let day: DayReconciliation
    let runs: [ProjectMetrics.Run]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(day.date).fontWeight(.semibold)
                Spacer()
                if let net = day.net {
                    Text("\(day.isToday ? "截至采集净增" : "实测净增") \(net > 0 ? "+\(net)" : String(net))")
                        .fontWeight(.semibold)
                } else {
                    Text("缺少前一天末次采样").foregroundStyle(.secondary)
                }
            }
            Text(publicReading).foregroundStyle(.secondary).font(.caption)
            if day.hasRoster || !day.additions.isEmpty {
                Text(archiveSummary).font(.caption)
            }
            if let baseline = day.baseline {
                Text("首份名单 \(ProjectMetrics.showTime(baseline.collectedAt))。此前的取消未留在加密归档中。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(day.removals) { event in
                Text("采集发现取消 · \(ProjectMetrics.fullTime(event.previousAt)) 至 \(ProjectMetrics.fullTime(event.detectedAt))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let window = day.cancellationWindow {
                Text("这段时间内有加星且前后总数相同。抵消可能发生在 \(window)，该区间没有两份完整名单可比对。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let first = runs.first, let last = runs.last {
                let starValues = Set(runs.map(\.stars))
                let stars = starValues.count == 1 ? "Star 均为 \(first.stars)" : "Star \(first.stars) → \(last.stars)"
                let forks = Set(runs.map(\.forks)).count == 1 ? "Fork 均为 \(first.forks)" : "Fork \(first.forks) → \(last.forks)"
                DisclosureGroup("Action \(runs.count) 次 · \(stars) · \(forks)") {
                    ForEach(runs) { sample in
                        HStack {
                            Text(ProjectMetrics.showTime(sample.collectedAt))
                            Spacer()
                            Text("Star \(sample.stars)")
                            Text("Fork \(sample.forks)")
                        }
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                    }
                }
                .font(.caption)
            }
            if !day.samples.isEmpty {
                DisclosureGroup("查看名单采样") {
                    ForEach(day.samples, id: \.collectedAt) { sample in
                        let changes = sample.changes
                        HStack {
                            Text(ProjectMetrics.showTime(sample.collectedAt))
                            Spacer()
                            Text("\(sample.users?.count ?? 0) 人")
                            if let changes {
                                Text("+\(changes.added.count) / −\(changes.removed.count)")
                            } else {
                                Text("首份名单")
                            }
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                    }
                }
                .font(.caption)
            }
        }
        .font(.subheadline.monospacedDigit())
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
    }

    private var publicReading: String {
        let ending = "\(day.after.count) 人（\(ProjectMetrics.showTime(day.after.collectedAt))）"
        guard let before = day.before else { return "当日末采 \(ending)" }
        return "前一日末采 \(before.count) 人（\(ProjectMetrics.showTime(before.collectedAt))） → 当日末采 \(ending)"
    }

    private var archiveSummary: String {
        let times = day.additions.reversed().map { ProjectMetrics.showTime($0.time) }.joined(separator: "、")
        let adds = times.isEmpty ? "未见有时间的加星" : "已知加星 \(day.additions.count) 人（\(times)）"
        guard !day.samples.isEmpty else { return adds }
        let detected = "名单采集 \(day.samples.count) 次 · 发现取消 \(day.removals.count) 人"
        guard let net = day.sampledNet else { return "\(adds) · \(detected)" }
        return "\(adds) · \(detected) · 当天首次到末次采样净变 \(net > 0 ? "+\(net)" : String(net))"
    }
}
