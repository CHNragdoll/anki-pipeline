import Foundation

struct MetricsWorkflow {
    private static let repository = "CHNragdoll/anki-pipeline"
    private static let workflow = "project-metrics.yml"
    static let page = URL(string: "https://github.com/\(repository)/actions/workflows/\(workflow)")!

    private struct Run: Decodable {
        let status: String
        let conclusion: String?
        let runStartedAt: Date?
        let updatedAt: Date?
        let runNumber: Int
        let runAttempt: Int
    }

    private struct RunList: Decodable {
        struct Entry: Decodable { let id: Int64 }
        let workflowRuns: [Entry]
    }

    struct Snapshot {
        let progress: Progress
        let runNumber: Int
        let runAttempt: Int
        let job: Job?
        let startedAt: Date?
        let completedAt: Date?
        let steps: [Step]
        let checkRunIDs: [Int64]

        var currentStep: Step? { steps.first { $0.status == "in_progress" } }

        func duration(at now: Date) -> String? {
            guard let startedAt else { return nil }
            if case .finished = progress, completedAt == nil { return nil }
            return MetricsWorkflow.duration(from: startedAt, to: completedAt ?? now)
        }
    }

    struct Step: Decodable, Identifiable {
        let name: String
        let number: Int
        let status: String
        let conclusion: String?
        let startedAt: Date?
        let completedAt: Date?

        var id: Int { number }
        var label: String { Progress.stepLabel(name) }

        var stateLabel: String {
            switch (status, conclusion) {
            case ("in_progress", _): "运行中"
            case ("completed", "success"): "完成"
            case ("completed", "skipped"): "跳过"
            case ("completed", "cancelled"): "取消"
            case ("completed", _): "失败"
            default: "未开始"
            }
        }

        func duration(at now: Date) -> String? {
            guard let startedAt, conclusion != "skipped" else { return nil }
            if let completedAt { return MetricsWorkflow.duration(from: startedAt, to: completedAt) }
            guard status == "in_progress" else { return nil }
            return MetricsWorkflow.duration(from: startedAt, to: now)
        }
    }

    private static func duration(from start: Date, to end: Date) -> String {
        let seconds = Int(max(0, end.timeIntervalSince(start)))
        return "\(seconds) 秒"
    }

    enum Progress {
        case queued
        case running(step: String?)
        case finished(conclusion: String?, failedStep: String?)

        var resultLabel: String? {
            guard case let .finished(conclusion, _) = self else { return nil }
            return MetricsWorkflow.conclusionLabel(conclusion)
        }

        var message: String {
            switch self {
            case .queued:
                return "已提交，等待 GitHub Actions 排队…"
            case .running(let step):
                return step.map { "正在\(Self.stepLabel($0))…" } ?? "GitHub Actions 正在运行…"
            case .finished("success", _):
                return "采集和部署已完成。"
            case .finished("cancelled", _):
                return "采集已取消。"
            case .finished(_, let step):
                return step.map { "步骤失败：\(Self.stepLabel($0))" } ?? "采集或部署未成功，请查看运行记录。"
            }
        }

        static func stepLabel(_ name: String) -> String {
            switch name {
            case "Set up job": return "准备运行环境"
            case let step where step.hasPrefix("Run actions/checkout@"): return "检出仓库"
            case "Restore accumulated history from the data-only branch": return "读取历史数据"
            case "Restore encrypted Star and Fork lists": return "读取 Star 和 Fork 归档"
            case "Collect official data and render SVGs": return "采集数据并生成图表"
            case "Encrypt Star and Fork lists before publishing": return "加密 Star 和 Fork 归档"
            case "Update only the dedicated data branch": return "保存采集结果"
            case "Add exam download pages and sitemap": return "生成下载页面"
            case "Upload public statistics site": return "上传站点文件"
            case "Wait for the Pages artifact to become visible": return "等待 Pages 接收站点文件"
            case "Deploy public statistics site": return "部署到 GitHub Pages"
            case "Remove temporary Star and Fork lists": return "清理临时归档"
            case "Complete job": return "完成收尾"
            case let step where step.hasPrefix("Post Run "): return "清理运行环境"
            default: return name
            }
        }
    }

    struct Job: Decodable {
        let id: Int64
        let name: String
        let status: String
        let conclusion: String?
        let steps: [Step]?
        let startedAt: Date?
        let completedAt: Date?

        var stateLabel: String {
            switch status {
            case "in_progress": "运行中"
            case "completed": MetricsWorkflow.conclusionLabel(conclusion)
            default: "排队中"
            }
        }

        func duration(at now: Date) -> String? {
            guard let startedAt else { return nil }
            if let completedAt { return MetricsWorkflow.duration(from: startedAt, to: completedAt) }
            guard status == "in_progress" else { return nil }
            return MetricsWorkflow.duration(from: startedAt, to: now)
        }
    }

    private struct Jobs: Decodable { let jobs: [Job] }

    private static func conclusionLabel(_ conclusion: String?) -> String {
        switch conclusion {
        case "success": "成功"
        case "failure", "startup_failure": "失败"
        case "cancelled": "已取消"
        case "timed_out": "超时"
        case "skipped": "已跳过"
        case "action_required": "需处理"
        case "neutral": "中性"
        case "stale": "已失效"
        default: "结果未知"
        }
    }

    private static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    enum RequestError: Error {
        case missingCLI
        case rejected
        case noRunID
    }

    private struct DispatchResponse: Decodable {
        let workflowRunID: Int64

        enum CodingKeys: String, CodingKey {
            case workflowRunID = "workflow_run_id"
        }
    }

    static func dispatch() async throws -> Int64 {
        let data = try await request([
            "--method", "POST", "repos/\(repository)/actions/workflows/\(workflow)/dispatches",
            "--raw-field", "ref=main", "--field", "return_run_details=true",
        ])
        guard let response = try? JSONDecoder().decode(DispatchResponse.self, from: data),
              response.workflowRunID > 0 else { throw RequestError.noRunID }
        return response.workflowRunID
    }

    static func latestManualRun() async throws -> Int64? {
        let data = try await request([
            "repos/\(repository)/actions/workflows/\(workflow)/runs?event=workflow_dispatch&branch=main&per_page=1"
        ])
        return try decoder().decode(RunList.self, from: data).workflowRuns.first?.id
    }

    static func progress(of id: Int64) async throws -> Snapshot {
        let endpoint = "repos/\(repository)/actions/runs/\(id)"
        async let runData = request([endpoint])
        async let jobsData = request(["\(endpoint)/jobs?filter=latest"])
        let (runResponse, jobsResponse) = try await (runData, jobsData)
        let run = try decoder().decode(Run.self, from: runResponse)
        let jobs = try decoder().decode(Jobs.self, from: jobsResponse).jobs
        let job = jobs.first { $0.name == "update" } ?? jobs.first
        let steps = (job?.steps ?? []).sorted { $0.number < $1.number }
        let activeStep = steps.first { $0.status == "in_progress" }
        let progress: Progress
        let hasStarted = run.status == "in_progress" || run.status == "completed" || job?.status == "in_progress"
        if run.status == "completed" {
            let failed = steps.first { $0.conclusion == "failure" }
            progress = .finished(conclusion: run.conclusion, failedStep: failed?.name)
        } else if hasStarted {
            progress = .running(step: activeStep?.name)
        } else {
            progress = .queued
        }
        let ended = run.status == "completed" ? jobs.compactMap(\.completedAt).max() ?? run.updatedAt : nil
        return Snapshot(progress: progress, runNumber: run.runNumber, runAttempt: run.runAttempt, job: job,
                        startedAt: hasStarted ? run.runStartedAt ?? job?.startedAt : nil,
                        completedAt: ended, steps: steps, checkRunIDs: jobs.map(\.id))
    }

    struct ResultDetails {
        let alerts: [Alert]?
        let artifacts: [Artifact]?

        struct Alert: Decodable {
            let annotationLevel: String
            let title: String?
            let message: String
            let rawDetails: String?
            let path: String?
            let startLine: Int?
            let endLine: Int?
            let startColumn: Int?
            let endColumn: Int?
            let blobHref: URL?

            var sourceURL: URL? {
                guard let blobHref, blobHref.scheme == "https", blobHref.host == "github.com" else { return nil }
                guard let startLine else { return blobHref }
                var components = URLComponents(url: blobHref, resolvingAgainstBaseURL: false)
                components?.fragment = endLine.map { $0 == startLine ? "L\(startLine)" : "L\(startLine)-L\($0)" }
                    ?? "L\(startLine)"
                return components?.url ?? blobHref
            }

            var sourceLocation: String? {
                guard let path, !path.isEmpty else { return nil }
                guard let startLine else { return path }
                let start = startColumn.map { "\(startLine):\($0)" } ?? String(startLine)
                let end = endLine.map { line in endColumn.map { "\(line):\($0)" } ?? String(line) }
                return end.map { $0 == start ? "\(path):\(start)" : "\(path):\(start)–\($0)" }
                    ?? "\(path):\(start)"
            }
        }

        struct Artifact: Decodable, Identifiable {
            let id: Int64
            let name: String
            let sizeInBytes: Int64
            let expired: Bool
        }
    }

    private struct ArtifactPage: Decodable {
        let artifacts: [ResultDetails.Artifact]
    }

    static func resultDetails(runID: Int64, checkRunIDs: [Int64]) async -> ResultDetails {
        async let alerts = loadAlerts(checkRunIDs)
        async let artifacts = loadArtifacts(runID)
        return await ResultDetails(alerts: alerts, artifacts: artifacts)
    }

    private static func loadAlerts(_ checkRunIDs: [Int64]) async -> [ResultDetails.Alert]? {
        var alerts: [ResultDetails.Alert] = []
        for id in checkRunIDs {
            guard let data = try? await request([
                "--paginate", "--slurp", "repos/\(repository)/check-runs/\(id)/annotations?per_page=100"
            ]), let pages = try? decoder().decode([[ResultDetails.Alert]].self, from: data) else {
                return nil
            }
            alerts.append(contentsOf: pages.joined())
        }
        return alerts
    }

    private static func loadArtifacts(_ id: Int64) async -> [ResultDetails.Artifact]? {
        guard let data = try? await request([
            "--paginate", "--slurp", "repos/\(repository)/actions/runs/\(id)/artifacts?per_page=100"
        ]), let pages = try? decoder().decode([ArtifactPage].self, from: data) else { return nil }
        return pages.flatMap(\.artifacts)
    }

    static func snapshotPage(runID: Int64, attempt: Int) -> URL {
        URL(string: "https://github.com/\(repository)/blob/project-metrics/runs/\(runID)/\(attempt)/snapshot.json")!
    }

    static func artifactPage(runID: Int64, artifactID: Int64) -> URL {
        page(for: runID).appendingPathComponent("artifacts").appendingPathComponent(String(artifactID))
    }

    static func page(for id: Int64) -> URL {
        URL(string: "https://github.com/\(repository)/actions/runs/\(id)")!
    }

    private static func request(_ arguments: [String]) async throws -> Data {
        try await Task.detached(priority: .utility) {
            guard let gh = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"]
                .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
                throw RequestError.missingCLI
            }
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: gh)
            process.arguments = ["api", "--hostname", "github.com"] + arguments
            var environment = ProcessInfo.processInfo.environment
            environment["GH_PROMPT_DISABLED"] = "1"
            process.environment = environment
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            process.standardInput = FileHandle.nullDevice
            try process.run()
            let timeout = DispatchWorkItem {
                if process.isRunning { process.terminate() }
            }
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 30, execute: timeout)
            defer { timeout.cancel() }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard process.terminationStatus == 0 else { throw RequestError.rejected }
            return data
        }.value
    }
}
