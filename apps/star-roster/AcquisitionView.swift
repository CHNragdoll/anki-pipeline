import SwiftUI
import UniformTypeIdentifiers

private struct GoogleReport: Decodable {
    struct SearchRow: Decodable {
        let keys: [String]
        let clicks: Int
        let impressions: Int
        let ctr: Double
        let position: Double
    }

    struct Search: Decodable {
        let days: [SearchRow]
        let pages: [SearchRow]
        let queries: [SearchRow]
    }

    struct Analytics: Decodable {
        struct Row: Decodable {
            let day: String
            let page: String
            let slot: String
            let count: Int
        }

        let rows: [Row]
        let timezone: String?
    }

    let search: Search?
    let analytics: Analytics?
    let searchError: String?
    let analyticsError: String?
    let error: String?
    let ok: Bool?

    static func read(_ arguments: [String]) async throws -> Self {
        try await Task.detached(priority: .utility) {
            guard let helper = Bundle.main.url(forResource: "google_reports", withExtension: "py") else {
                throw CocoaError(.fileNoSuchFile)
            }
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            process.arguments = [helper.path] + arguments
            process.standardInput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            process.standardOutput = pipe
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard process.terminationStatus == 0 else { throw CocoaError(.executableLoad) }
            return try JSONDecoder().decode(Self.self, from: data)
        }.value
    }
}

private struct AcquisitionGitHub: Decodable {
    struct Daily: Decodable {
        let count: Int
        let uniques: Int
    }

    struct History: Decodable {
        let views: [String: Daily]
        let clones: [String: Daily]
    }

    struct Slot: Decodable, Identifiable {
        struct Point: Decodable {
            let day: String
            let total: Int
            let change: Int?
            let partial: Bool
        }

        let id: String
        let label: String
        let points: [Point]
        let utcPoints: [Point]
    }

    let history: History
    let downloadSlots: [Slot]

    static func load() async throws -> Self {
        let url = ProjectMetrics.pageURL.appendingPathComponent("snapshot.json")
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: data)
    }
}

@MainActor
private final class AcquisitionModel: ObservableObject {
    @Published var google: GoogleReport?
    @Published var github: AcquisitionGitHub?
    @Published var githubError: String?
    @Published var googleError: String?
    @Published var connecting = false
    @Published var loading = false
    @Published var range = 28
    @Published var day = ""
    @Published var page = ""
    @Published var slot = ""

    func refresh(property: String) async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        let requestedRange = range
        async let git = try? AcquisitionGitHub.load()
        async let report = try? GoogleReport.read(["report", "--days", String(requestedRange),
                                                  "--property", property.trimmingCharacters(in: .whitespacesAndNewlines)])
        let (github, google) = await (git, report)
        self.github = github
        githubError = github == nil ? "无法读取 GitHub 项目数据。" : nil
        self.google = google
        googleError = google?.error ?? (google == nil ? "无法启动或读取本地 Google 报表工具。" : nil)
    }

    func connect(file: URL, property: String) async {
        guard !connecting else { return }
        connecting = true
        defer { connecting = false }
        do {
            let response = try await GoogleReport.read(["connect", file.path])
            guard response.ok == true else {
                googleError = response.error ?? "Google 授权未完成。"
                return
            }
        } catch {
            googleError = "无法启动本地 Google 授权工具。"
            return
        }
        await refresh(property: property)
    }
}

struct AcquisitionView: View {
    let refreshID: Int
    let timeZone: MetricsTimeZone
    @StateObject private var model = AcquisitionModel()
    @AppStorage("acquisitionGA4Property") private var property = ""

    private var days: [String] {
        let github = model.github
        let dates = Set(github?.history.views.keys.map { $0 } ?? [])
            .union(github?.history.clones.keys.map { $0 } ?? [])
            .union(model.google?.search?.days.compactMap { $0.keys.first } ?? [])
            .union(model.google?.analytics?.rows.map(\.day) ?? [])
            .union(github?.downloadSlots.flatMap { points($0).map(\.day) } ?? [])
        return Array(dates.sorted(by: >).prefix(model.range))
    }

    private var pages: [String] {
        let search = model.google?.search?.pages.compactMap { $0.keys.dropFirst().first }.map(path) ?? []
        return Set(search).union(model.google?.analytics?.rows.map(\.page) ?? []).sorted()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("搜索与下载").font(.title2.bold())
                controls
                githubCard
                searchCard
                analyticsCard
                downloadsCard
            }
            .frame(maxWidth: 1100, alignment: .leading)
            .padding(20)
            .frame(maxWidth: .infinity)
        }
        .background(Color(nsColor: .underPageBackgroundColor))
        .task(id: refreshID) { await model.refresh(property: property) }
    }

    private var controls: some View {
        card("数据源与筛选") {
            HStack {
                Button("连接 Google") {
                    let panel = NSOpenPanel()
                    panel.allowedContentTypes = [.json]
                    panel.message = "选择 Google Cloud 下载的桌面应用 OAuth 客户端 JSON"
                    panel.begin { response in
                        if response == .OK, let url = panel.url {
                            Task { await model.connect(file: url, property: property) }
                        }
                    }
                }
                .disabled(model.connecting || model.loading)
                TextField("GA4 Property ID", text: $property).frame(maxWidth: 165)
                Button("读取数据") { Task { await model.refresh(property: property) } }
                    .disabled(model.loading || model.connecting)
                if model.loading || model.connecting { ProgressView().controlSize(.small) }
            }
            if model.connecting { Text("请在浏览器完成 Google 只读授权。").foregroundStyle(.secondary) }
            if let error = model.googleError { Text(error).foregroundStyle(.secondary) }
            HStack {
                Picker("范围", selection: $model.range) {
                    ForEach([7, 28, 90], id: \.self) { Text("近 \($0) 天").tag($0) }
                }
                .onChange(of: model.range) { _, _ in
                    model.day = ""
                    Task { await model.refresh(property: property) }
                }
                .disabled(model.loading || model.connecting)
                Picker("日期", selection: $model.day) {
                    Text("整个范围").tag("")
                    ForEach(days, id: \.self) { Text($0).tag($0) }
                }
            }
            if !pages.isEmpty {
                Picker("Pages 落地页", selection: $model.page) {
                    Text("所有页面").tag("")
                    ForEach(pages, id: \.self) { Text($0).tag($0) }
                }
            }
            if let slots = model.github?.downloadSlots {
                Picker("下载栏目", selection: $model.slot) {
                    Text("所有栏目").tag("")
                    ForEach(slots) { Text($0.label).tag($0.id) }
                }
            }
            Text("来源各用自己的日界。GitHub 流量为 UTC，Search Console 为美西时间，GA4 用属性时区。Release 下载量涵盖所有入口。")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var githubCard: some View {
        card("GitHub 仓库流量") {
            if let github = model.github {
                let selected = days.filter(inDate)
                if !selected.contains(where: { github.history.views[$0] != nil || github.history.clones[$0] != nil }) {
                    Text("所选日期暂无已采集数据。").foregroundStyle(.secondary)
                }
                ForEach(selected.filter { github.history.views[$0] != nil || github.history.clones[$0] != nil }, id: \.self) { day in
                    let views = github.history.views[day]
                    let clones = github.history.clones[day]
                    row(day, "浏览 \(show(views?.count)) · 访客 \(show(views?.uniques)) · 克隆 \(show(clones?.count)) · 独立克隆 \(show(clones?.uniques))")
                }
            } else if let error = model.githubError {
                Text(error).foregroundStyle(.secondary)
            }
            Link("仓库来源网站与热门页面快照", destination: sectionURL("popular-traffic"))
        }
    }

    private var searchCard: some View {
        card("Google Search Console") {
            if let search = model.google?.search {
                let totals = model.page.isEmpty ? search.days.filter { matchesSearch($0, pageFilter: false) }
                    : search.pages.filter { matchesSearch($0) }
                if totals.isEmpty {
                    Text("所选范围暂无 Google 已返回的搜索数据。").foregroundStyle(.secondary)
                } else {
                    let clicks = totals.reduce(0) { $0 + $1.clicks }
                    let impressions = totals.reduce(0) { $0 + $1.impressions }
                    let rate = impressions > 0 ? Double(clicks) / Double(impressions) : 0
                    Text("\(clicks) 次点击 · \(impressions) 次展示 · 点击率 \(rate.formatted(.percent.precision(.fractionLength(1))))")
                }
                Text("落地页").fontWeight(.semibold)
                ForEach(Array(search.pages.filter { matchesSearch($0) }.sorted { $0.clicks > $1.clicks }.enumerated()), id: \.offset) { _, entry in
                    if let page = entry.keys.dropFirst().first { row("\(entry.keys[0]) · \(path(page))", searchSummary(entry)) }
                }
                Text("搜索词与落地页").fontWeight(.semibold)
                let queries = search.queries.filter { matchesSearch($0) }.sorted { $0.clicks > $1.clicks }
                if queries.isEmpty { Text("Google 暂无可返回的查询词明细。").foregroundStyle(.secondary) }
                ForEach(Array(queries.enumerated()), id: \.offset) { _, entry in
                    if entry.keys.count == 3 {
                        row("\(entry.keys[0]) · \(entry.keys[2]) · \(path(entry.keys[1]))", searchSummary(entry))
                    }
                }
            } else if let error = model.google?.searchError {
                Text(error).foregroundStyle(.secondary)
            }
            Link("打开 Google Search Console", destination: URL(string: "https://search.google.com/search-console")!)
        }
    }

    private var analyticsCard: some View {
        card("GA4 下载按钮点击") {
            if let analytics = model.google?.analytics {
                let records = analytics.rows.filter {
                    inDate($0.day) && (model.page.isEmpty || $0.page == model.page)
                        && (model.slot.isEmpty || $0.slot == model.slot)
                }
                if records.isEmpty {
                    Text("所选范围暂无已采集的点击事件。").foregroundStyle(.secondary)
                } else {
                    Text("属性时区 \(analytics.timezone ?? "由 GA4 属性决定")")
                    let labels = Dictionary(uniqueKeysWithValues: (model.github?.downloadSlots ?? []).map { ($0.id, $0.label) })
                    ForEach(Array(records.sorted { ($0.day, $0.count) > ($1.day, $1.count) }.enumerated()), id: \.offset) { _, entry in
                        row("\(entry.day) · \(entry.page) · \(labels[entry.slot] ?? entry.slot)", "\(entry.count) 次")
                    }
                }
            } else if let error = model.google?.analyticsError {
                Text(error).foregroundStyle(.secondary)
            }
        }
    }

    private var downloadsCard: some View {
        card("GitHub Release 实际下载") {
            if let github = model.github {
                let slots = github.downloadSlots.filter { model.slot.isEmpty || $0.id == model.slot }
                if model.day.isEmpty, let slot = slots.first, !model.slot.isEmpty {
                    Text("\(slot.label) · \(timeZone.label) · 各版本合计")
                        .foregroundStyle(.secondary)
                    ForEach(points(slot).filter { days.contains($0.day) }.reversed(), id: \.day) { point in
                        row(point.day, downloadSummary(point))
                    }
                } else {
                    let selectedDay = model.day.isEmpty ? days.first : model.day
                    Text("\(selectedDay ?? "暂无日期") · \(timeZone.label) · 各版本合计")
                        .foregroundStyle(.secondary)
                    ForEach(slots) { slot in
                        if let point = points(slot).first(where: { $0.day == selectedDay }) {
                            row(slot.label, downloadSummary(point))
                        }
                    }
                }
            }
            Link("查看各下载栏目与附件版本", destination: sectionURL("download-slots"))
        }
    }

    private func card<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(title).font(.headline)
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background, in: RoundedRectangle(cornerRadius: 10))
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
            Spacer(minLength: 8)
            Text(value).monospacedDigit().foregroundStyle(.secondary)
        }
        .font(.subheadline)
    }

    private func inDate(_ value: String) -> Bool { model.day.isEmpty || model.day == value }
    private func sectionURL(_ section: String) -> URL {
        URL(string: "#" + section, relativeTo: ProjectMetrics.pageURL)!.absoluteURL
    }
    private func path(_ url: String) -> String {
        guard let parsed = URL(string: url), parsed.host != nil else { return url }
        return parsed.path + (url.hasSuffix("/") && !parsed.path.hasSuffix("/") ? "/" : "")
    }
    private func show(_ number: Int?) -> String { number.map { $0.formatted() } ?? "—" }
    private func points(_ slot: AcquisitionGitHub.Slot) -> [AcquisitionGitHub.Slot.Point] {
        timeZone == .utc ? slot.utcPoints : slot.points
    }
    private func downloadSummary(_ point: AcquisitionGitHub.Slot.Point) -> String {
        "累计 \(point.total) · 增量 \(show(point.change))\(point.partial ? " · 部分采样" : "")"
    }

    private func matchesSearch(_ row: GoogleReport.SearchRow, pageFilter: Bool = true) -> Bool {
        guard let date = row.keys.first, inDate(date) else { return false }
        return !pageFilter || model.page.isEmpty || row.keys.dropFirst().first.map(path) == model.page
    }
    private func searchSummary(_ row: GoogleReport.SearchRow) -> String {
        let ctr = row.ctr.formatted(.percent.precision(.fractionLength(1)))
        let position = row.position.formatted(.number.precision(.fractionLength(1)))
        return "\(row.clicks) 点击 · \(row.impressions) 展示 · \(ctr) · 平均排名 \(position)"
    }
}
