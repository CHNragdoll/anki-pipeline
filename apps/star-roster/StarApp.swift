import SwiftUI

private let chinese = Locale(identifier: "zh_CN")
private let accent = Color.accentColor
private let canvas = Color(nsColor: .underPageBackgroundColor)
private let surface = Color(nsColor: .controlBackgroundColor)

enum MetricsTimeZone: String, CaseIterable, Identifiable {
    case beijing = "Asia/Shanghai"
    case utc = "UTC"

    var id: Self { self }
    var label: String { self == .beijing ? "北京时间" : "UTC" }
    var value: TimeZone { TimeZone(identifier: rawValue)! }

    var clock: Date.VerbatimFormatStyle {
        .init(format: "\(hour: .twoDigits(clock: .twentyFourHour, hourCycle: .zeroBased)):\(minute: .twoDigits):\(second: .twoDigits)",
              locale: chinese, timeZone: value, calendar: Calendar(identifier: .gregorian))
    }

    var day: Date.VerbatimFormatStyle {
        .init(format: "\(year: .defaultDigits)-\(month: .twoDigits)-\(day: .twoDigits)",
              locale: chinese, timeZone: value, calendar: Calendar(identifier: .gregorian))
    }
}

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
    let gitHistory = GitHistoryModel()
    @Published private(set) var workflowStatus: String?
    @Published private(set) var workflowRunID: Int64?
    @Published private(set) var workflowActive = false
    @Published private(set) var workflowSnapshot: MetricsWorkflow.Snapshot?
    @Published private(set) var workflowResult: MetricsWorkflow.ResultDetails?
    @Published var workflowDetailsOpen = false
    private let archive = Archive()

    func refreshAll() async {
        projectRefreshID += 1
        gitHistory.syncOrigin(refreshID: projectRefreshID)
        await refresh()
    }

    func runMetricsWorkflow() async {
        guard !workflowActive else { return }
        workflowActive = true
        workflowRunID = nil
        workflowSnapshot = nil
        workflowResult = nil
        workflowStatus = "正在请求 GitHub Actions…"
        defer { workflowActive = false }

        let runID: Int64
        do {
            runID = try await MetricsWorkflow.dispatch()
        } catch MetricsWorkflow.RequestError.missingCLI {
            workflowStatus = "未找到 GitHub CLI（gh）。"
            return
        } catch MetricsWorkflow.RequestError.noRunID {
            workflowStatus = "GitHub 已接受请求，但未返回运行编号。请在运行记录中查看。"
            return
        } catch {
            workflowStatus = "无法确认采集请求。请先查看运行记录，并检查 GitHub 登录和权限。"
            return
        }

        await followWorkflow(runID, refreshIfComplete: true)
    }

    func restoreWorkflow() async {
        guard workflowRunID == nil, !workflowActive,
              let runID = try? await MetricsWorkflow.latestManualRun(),
              !Task.isCancelled, workflowRunID == nil, !workflowActive else { return }
        workflowActive = true
        defer { workflowActive = false }
        await followWorkflow(runID, refreshIfComplete: false)
    }

    private func followWorkflow(_ runID: Int64, refreshIfComplete: Bool) async {
        workflowRunID = runID
        workflowStatus = "正在读取 GitHub Actions 状态…"
        var observedRunning = refreshIfComplete
        let clock = ContinuousClock()
        let deadline = clock.now + .seconds(900)
        while clock.now < deadline {
            do {
                try Task.checkCancellation()
                let snapshot = try await MetricsWorkflow.progress(of: runID)
                workflowSnapshot = snapshot
                let progress = snapshot.progress
                workflowStatus = progress.message
                if case .finished(let conclusion, _) = progress {
                    async let details = MetricsWorkflow.resultDetails(runID: runID, checkRunIDs: snapshot.checkRunIDs)
                    if conclusion == "success", observedRunning {
                        workflowStatus = "采集和部署已完成，正在刷新项目数据。"
                        await refreshAll()
                    }
                    workflowResult = await details
                    workflowStatus = progress.message
                    return
                }
                observedRunning = true
            } catch is CancellationError {
                return
            } catch {
                workflowStatus = "暂时无法读取运行状态，正在重试…"
            }
            do {
                try await Task.sleep(for: .seconds(2))
            } catch {
                return
            }
        }
        workflowStatus = "等待超时，GitHub 可能仍在运行。请查看运行记录。"
    }

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
    @AppStorage("metricsTimeZone") private var timeZone = MetricsTimeZone.beijing

    private var clock: Date.VerbatimFormatStyle { timeZone.clock }
    private var day: Date.VerbatimFormatStyle { timeZone.day }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            banner
            Divider()
            tabs(model.roster)
            Divider()
            if model.tab == .project {
                if let status = model.workflowStatus {
                    workflowNotice(status)
                }
                ProjectDashboard(roster: model.roster, gitHistory: model.gitHistory,
                                 refreshID: model.projectRefreshID, timeZone: timeZone)
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
        .onChange(of: model.tab) { _, tab in
            if tab == .project { Task { await model.restoreWorkflow() } }
        }
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
            Picker("统计时区", selection: $timeZone) {
                ForEach(MetricsTimeZone.allCases) { zone in
                    Text(zone.label).tag(zone)
                }
            }
            .labelsHidden()
            .accessibilityLabel("统计时区")
            .accessibilityIdentifier("metrics-timezone")
            .fixedSize()
            if model.tab == .project {
                Button {
                    Task { await model.runMetricsWorkflow() }
                } label: {
                    Label("立即采集", systemImage: "play.circle")
                }
                .fixedSize()
                .disabled(model.workflowActive)
                .help("运行 GitHub Actions 的 Project metrics，部署完成后自动刷新")
                .accessibilityIdentifier("metrics-run-workflow")
            }
            Button {
                Task { await model.refreshAll() }
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

    private func workflowNotice(_ message: String) -> some View {
        TimelineView(.animation(minimumInterval: 1, paused: !model.workflowActive)) { context in
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    if model.workflowActive {
                        ProgressView().controlSize(.small).accessibilityHidden(true)
                    }
                    if let progress = model.workflowSnapshot?.progress, let result = progress.resultLabel {
                        workflowBadge(result)
                    }
                    Text(message).layoutPriority(1)
                    Spacer(minLength: 8)
                    if model.workflowSnapshot != nil {
                        Button {
                            model.workflowDetailsOpen.toggle()
                        } label: {
                            Label(model.workflowDetailsOpen ? "收起详情" : "步骤与结果",
                                  systemImage: model.workflowDetailsOpen ? "chevron.up" : "chevron.down")
                        }
                        .accessibilityIdentifier("metrics-workflow-details")
                        .fixedSize()
                    }
                    Link("运行记录", destination: model.workflowRunID.map(MetricsWorkflow.page(for:)) ?? MetricsWorkflow.page)
                        .fixedSize()
                }
                if let snapshot = model.workflowSnapshot {
                    workflowTiming(snapshot, at: context.date)
                    if model.workflowDetailsOpen {
                        Divider()
                        ScrollView {
                            VStack(alignment: .leading, spacing: 12) {
                                if let result = model.workflowResult {
                                    workflowResults(result)
                                }
                                if !snapshot.steps.isEmpty {
                                    workflowSteps(snapshot.steps, at: context.date)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 4)
                        }
                        .frame(height: 224)
                    }
                }
            }
        }
        .font(.caption)
        .padding(.horizontal, 24)
        .padding(.vertical, 8)
        .background(surface)
        .overlay(alignment: .bottom) { Divider() }
    }

    private func workflowTiming(_ snapshot: MetricsWorkflow.Snapshot, at date: Date) -> some View {
        HStack(spacing: 16) {
            Text(verbatim: "#\(snapshot.runNumber)")
            if let total = snapshot.duration(at: date) {
                Text("总用时 \(total)")
            }
            if let current = snapshot.currentStep?.duration(at: date) {
                Text("当前步骤 \(current)")
            }
            if let job = snapshot.job {
                let label = job.duration(at: date).map { "\(job.name) · \(job.stateLabel) · \($0)" }
                    ?? "\(job.name) · \(job.stateLabel)"
                Text(label)
            }
            if let result = model.workflowResult {
                if let alerts = result.alerts {
                    Text("\(alerts.count) 条 Annotations")
                }
                if let artifacts = result.artifacts {
                    Text("\(artifacts.count) 个产物")
                }
            }
        }
        .monospacedDigit()
        .foregroundStyle(.secondary)
    }

    private func workflowBadge(_ label: String) -> some View {
        let success = label == "成功"
        let failed = label == "失败" || label == "超时"
        let color: Color = success ? .green : failed ? .red : .secondary
        return Label(label, systemImage: success ? "checkmark.circle.fill" : failed ? "xmark.circle.fill" : "info.circle")
            .fontWeight(.semibold)
            .foregroundStyle(color)
            .fixedSize()
    }

    private func workflowSteps(_ steps: [MetricsWorkflow.Step], at date: Date) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("步骤用时").fontWeight(.semibold)
            ForEach(steps) { step in
                HStack(spacing: 12) {
                    Text(step.label).help(step.name)
                    Spacer()
                    Text(step.stateLabel).foregroundStyle(.secondary)
                    Text(step.duration(at: date) ?? "—")
                        .monospacedDigit()
                        .frame(minWidth: 56, alignment: .trailing)
                }
            }
        }
    }

    private func workflowResults(_ result: MetricsWorkflow.ResultDetails) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("运行结果").fontWeight(.semibold)
            if let snapshot = model.workflowSnapshot, let runID = model.workflowRunID {
                if snapshot.steps.contains(where: {
                    $0.name == "Deploy public statistics site" && $0.conclusion == "success"
                }) {
                    Link("查看已部署的项目数据", destination: ProjectMetrics.pageURL)
                }
                if snapshot.steps.contains(where: {
                    $0.name == "Update only the dedicated data branch" && $0.conclusion == "success"
                }) {
                    Link("查看本次采集快照 JSON",
                         destination: MetricsWorkflow.snapshotPage(runID: runID, attempt: snapshot.runAttempt))
                }
            }
            Text("Annotations").fontWeight(.semibold)
            if let alerts = result.alerts {
                if alerts.isEmpty { Text("本次运行没有 Annotations。").foregroundStyle(.secondary) }
                ForEach(Array(alerts.enumerated()), id: \.offset) { index, alert in
                    if index > 0 { Divider() }
                    workflowAnnotation(alert)
                }
            } else {
                Text("Annotations 读取失败，请查看运行记录。").foregroundStyle(.secondary)
            }
            Text("Artifacts").fontWeight(.semibold)
            if let artifacts = result.artifacts {
                if artifacts.isEmpty { Text("本次运行没有生成 Artifacts。").foregroundStyle(.secondary) }
                ForEach(artifacts) { artifact in
                    HStack(spacing: 12) {
                        if !artifact.expired, let runID = model.workflowRunID {
                            Link(artifact.name, destination: MetricsWorkflow.artifactPage(runID: runID, artifactID: artifact.id))
                        } else {
                            Text(artifact.name)
                            Text("已过期").foregroundStyle(.secondary)
                        }
                        Text(ByteCountFormatter.string(fromByteCount: artifact.sizeInBytes, countStyle: .file))
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text("Artifacts 读取失败，请查看运行记录。").foregroundStyle(.secondary)
            }
        }
    }

    private func workflowAnnotation(_ alert: MetricsWorkflow.ResultDetails.Alert) -> some View {
        let color: Color = alert.annotationLevel == "failure" ? .red
            : alert.annotationLevel == "warning" ? .orange : .accentColor
        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Text(verbatim: alert.annotationLevel).foregroundStyle(color)
                if let title = alert.title, !title.isEmpty {
                    Text(verbatim: title)
                }
            }
            .fontWeight(.semibold)
            if let location = alert.sourceLocation {
                if let source = alert.sourceURL {
                    Link(location, destination: source).help(source.absoluteString)
                } else {
                    Text(verbatim: location).textSelection(.enabled)
                }
            } else if let source = alert.sourceURL {
                Link("查看源文件", destination: source).help(source.absoluteString)
            }
            Text(verbatim: alert.message).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            if let details = alert.rawDetails, !details.isEmpty {
                Text("原始详情").foregroundStyle(.secondary)
                Text(verbatim: details)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
            Text("\(timeZone.label) · 从晚到早")
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
