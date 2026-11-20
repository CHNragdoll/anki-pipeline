import SwiftUI

struct Fork: Decodable, Identifiable {
    let id: Int64
    let fullName: String
    let createdAt: Date
    let ownerID: Int64?

    private enum CodingKeys: String, CodingKey {
        case id, fullName, createdAt, ownerId, owner
    }

    private struct Owner: Decodable { let id: Int64 }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(Int64.self, forKey: .id)
        fullName = try values.decode(String.self, forKey: .fullName)
        createdAt = try values.decode(Date.self, forKey: .createdAt)
        ownerID = try values.decodeIfPresent(Int64.self, forKey: .ownerId)
            ?? values.decodeIfPresent(Owner.self, forKey: .owner)?.id
    }

    var url: URL {
        URL(string: "https://github.com")!.appendingPathComponent(fullName)
    }
}

struct ForkSample: Decodable {
    struct Changes: Decodable {
        let previousAt: Date
        let added: [Fork]
        let removed: [Fork]
    }
    let collectedAt: Date
    let forks: [Fork]?
    let changes: Changes?
}

private struct ForkHistory {
    let totals: [ProjectMetrics.Run]
    let privateSamples: [ForkSample]
    let missing: Int
}

private enum ForkData {
    static func current() async throws -> [Fork] {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        let session = URLSession(configuration: configuration)
        var page: URL? = URL(string: "https://api.github.com/repos/CHNragdoll/anki-pipeline/forks?per_page=100")
        var forks: [Int64: Fork] = [:]
        while let url = page {
            try Task.checkCancellation()
            let (data, response) = try await session.data(from: url)
            guard let http = response as? HTTPURLResponse else { throw RosterError.invalidResponse }
            if http.statusCode == 429 || (http.statusCode == 403 && http.value(forHTTPHeaderField: "x-ratelimit-remaining") == "0") {
                return try authenticatedForks()
            }
            guard http.statusCode == 200 else { throw RosterError.invalidResponse }
            for fork in try Archive().decoder().decode([Fork].self, from: data) { forks[fork.id] = fork }
            let links = http.value(forHTTPHeaderField: "Link")?.components(separatedBy: ",") ?? []
            page = links.first { $0.contains("rel=\"next\"") }
                .flatMap { $0.split(separator: "<", maxSplits: 1).last?.split(separator: ">").first }
                .flatMap { URL(string: String($0)) }
        }
        return forks.values.sorted { $0.createdAt > $1.createdAt }
    }

    private static func authenticatedForks() throws -> [Fork] {
        guard let gh = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"].first(where: FileManager.default.isExecutableFile(atPath:))
        else { throw RosterError.rateLimit }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: gh)
        process.arguments = ["api", "--paginate", "--slurp", "repos/CHNragdoll/anki-pipeline/forks?per_page=100"]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw RosterError.rateLimit }
        let pages = try Archive().decoder().decode([[Fork]].self, from: data)
        return Dictionary(pages.joined().map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
            .values.sorted { $0.createdAt > $1.createdAt }
    }

    static func history() async throws -> ForkHistory {
        let archive = Archive()
        let paths = try await archive.recordedPaths(["snapshot.json", "forks.json.gpg"])
        let totalPaths = paths["snapshot.json"] ?? []
        let rosterPaths = paths["forks.json.gpg"] ?? []

        async let totals = archive.readBatch(totalPaths) { path in
            try archive.decoder().decode(ProjectMetrics.Run.self, from: await archive.publicRun(path: path))
        }
        async let samples = archive.readBatch(rosterPaths) { path in
            try await archive.encryptedForkRun(path: path)
        }
        let (publicRows, privateRows) = await (totals, samples)
        let complete = privateRows.filter { $0.forks != nil }
        return ForkHistory(totals: ProjectMetrics.uniqueRuns(publicRows),
                           privateSamples: complete.sorted { $0.collectedAt > $1.collectedAt },
                           missing: totalPaths.count + rosterPaths.count - publicRows.count - complete.count)
    }


}

@MainActor
private final class ForkModel: ObservableObject {
    @Published var forks: [Fork]?
    @Published var history: ForkHistory?
    @Published var currentError = false
    @Published var historyError = false

    func load() async {
        async let current: [Fork]? = try? ForkData.current()
        async let saved: ForkHistory? = try? ForkData.history()
        let currentResult = await current
        guard !Task.isCancelled else { return }
        currentError = currentResult == nil
        if let currentResult { forks = currentResult }
        let savedResult = await saved
        guard !Task.isCancelled else { return }
        historyError = savedResult == nil
        if let savedResult { history = savedResult }
    }
}

struct ForksView: View {
    let refreshID: Int
    @StateObject private var model = ForkModel()

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                Text("Fork").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
                Text("北京时间 · 当前列表来自 GitHub，历史总数来自 Action 逐次采样。")
                    .font(.subheadline).foregroundStyle(.secondary)
                group("当前公开 Fork") {
                    if let forks = model.forks {
                        if forks.isEmpty { Text("暂无公开 Fork。") }
                        ForEach(forks) { fork in
                            HStack(spacing: 12) {
                                if let ownerID = fork.ownerID {
                                    AvatarView(star: Star(id: ownerID, login: String(fork.fullName.split(separator: "/")[0]),
                                                          starredAt: nil))
                                }
                                forkLink(fork)
                                Spacer(minLength: 10)
                                Text(ProjectMetrics.fullTime(fork.createdAt))
                                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 3)
                        }
                    }
                    if model.currentError {
                        Text("当前列表读取失败，请刷新。").foregroundStyle(.secondary)
                    } else if model.forks == nil {
                        ProgressView().controlSize(.small)
                    }
                }
                group("已归档的 Fork 名单变化") {
                    if let history = model.history {
                        if let first = history.privateSamples.last {
                            Text("完整名单从 \(ProjectMetrics.fullTime(first.collectedAt)) 开始留档。")
                                .font(.caption).foregroundStyle(.secondary)
                            let changes = history.privateSamples.filter {
                                guard let change = $0.changes else { return false }
                                return !change.added.isEmpty || !change.removed.isEmpty
                            }
                            if changes.isEmpty { Text("已归档名单暂无增减。") }
                            ForEach(changes, id: \.collectedAt) { sample in
                                if let change = sample.changes {
                                    Text(ProjectMetrics.fullTime(sample.collectedAt)).font(.caption.monospacedDigit())
                                    ForEach(change.added) { fork in
                                        HStack { Text("新增").foregroundStyle(.green); forkLink(fork) }
                                    }
                                    ForEach(change.removed) { fork in
                                        HStack { Text("采集发现移除").foregroundStyle(.red); forkLink(fork) }
                                    }
                                }
                            }
                        } else {
                            Text("当前归档还没有完整 Fork 名单，只有历史总数。")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                    } else if model.historyError {
                        Text("Action 归档读取失败，请刷新。")
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                if let history = model.history {
                    group("Action 采样总数 · \(history.totals.count) 次") {
                        if history.missing > 0 {
                            Text("\(history.missing) 份归档读取失败或名单不完整。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(history.totals) { sample in
                            HStack {
                                Text(ProjectMetrics.fullTime(sample.collectedAt))
                                Spacer()
                                Text("\(sample.forks) 个")
                            }
                            .font(.subheadline.monospacedDigit())
                        }
                    }
                }
            }
            .frame(maxWidth: 800)
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .task(id: refreshID) { await model.load() }
    }

    private func forkLink(_ fork: Fork) -> some View {
        Link(fork.fullName, destination: fork.url)
            .font(.subheadline.weight(.semibold))
            .handCursor()
    }

    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
    }
}
