import Foundation

struct Star: Decodable {
    let id: Int64
    let login: String
    let starredAt: Date?

    var profileURL: URL {
        URL(string: "https://github.com")!.appendingPathComponent(login)
    }

    var avatarURL: URL { avatarURL(size: 80) }

    func avatarURL(size: Int) -> URL {
        URL(string: "https://avatars.githubusercontent.com/u/\(id)?s=\(size)&v=4")!
    }
}

struct Snapshot: Decodable {
    struct Changes: Decodable {
        let previousAt: Date
        let added: [Star]
        let removed: [Star]
    }

    let collectedAt: Date
    let users: [Star]?
    let changes: Changes?
}

struct StarEvent: Identifiable {
    let star: Star
    let detectedAt: Date
    let previousAt: Date
    let added: Bool
    var baseline = false

    var exactTime: Date? {
        guard added, let time = star.starredAt, time <= detectedAt else { return nil }
        return time
    }

    var time: Date { exactTime ?? detectedAt }
    var id: String { "\(detectedAt.timeIntervalSince1970):\(added):\(star.id)" }
}

struct Roster {
    let snapshots: [Snapshot]
    let unavailable: Int
    let nonComparable: Int

    var latest: Snapshot? { snapshots.last }

    var events: [StarEvent] {
        let changes = snapshots.flatMap { snapshot -> [StarEvent] in
            guard let changes = snapshot.changes else { return [] }
            return [(true, changes.added), (false, changes.removed)].flatMap { added, stars in
                stars.map { StarEvent(star: $0, detectedAt: snapshot.collectedAt,
                                     previousAt: changes.previousAt, added: added) }
            }
        }
        var history: [StarEvent] = []
        if let first = snapshots.first, first.changes == nil {
            history = (first.users ?? []).compactMap { star in
                guard let time = star.starredAt, time <= first.collectedAt else { return nil }
                return StarEvent(star: star, detectedAt: first.collectedAt,
                                 previousAt: first.collectedAt, added: true, baseline: true)
            }
        }
        return (changes + history).sorted {
            ($0.time, $0.detectedAt, $0.id) > ($1.time, $1.detectedAt, $1.id)
        }
    }

    var members: [Star] {
        (latest?.users ?? []).sorted {
            ($0.starredAt ?? .distantPast, $0.id) > ($1.starredAt ?? .distantPast, $1.id)
        }
    }
}

enum RosterError: LocalizedError {
    case noKey, noGPG, invalidResponse, rateLimit, invalidTree, decrypt, noHistory

    var errorDescription: String? {
        switch self {
        case .noKey: "找不到现有的本机解密文件。"
        case .noGPG: "找不到本机 GPG。"
        case .invalidResponse: "GitHub 请求失败，请检查网络后刷新。"
        case .rateLimit: "GitHub 暂时限制了请求次数，请稍后刷新。"
        case .invalidTree: "GitHub 未返回完整的归档目录。"
        case .decrypt: "无法用现有密钥解密名单。"
        case .noHistory: "暂时没有可读取的完整 Star 名单。"
        }
    }
}

struct Archive {
    private struct Tree: Decodable {
        struct Entry: Decodable {
            let path: String
            let type: String
        }

        let tree: [Entry]
        let truncated: Bool
    }

    private let key = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".local/share/anki-pipeline/star-roster/passphrase")
    private let api = URL(string: "https://api.github.com/repos/CHNragdoll/anki-pipeline")!
    private let raw = URL(string: "https://raw.githubusercontent.com/CHNragdoll/anki-pipeline/project-metrics")!
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 22
        config.timeoutIntervalForResource = 40
        return URLSession(configuration: config)
    }()

    func load() async throws -> Roster {
        guard FileManager.default.isReadableFile(atPath: key.path) else { throw RosterError.noKey }
        guard let gpg = ["/opt/homebrew/bin/gpg", "/usr/local/bin/gpg", "/usr/local/MacGPG2/bin/gpg"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { throw RosterError.noGPG }

        let paths = try await recordedPaths(["stargazers.json.gpg"])["stargazers.json.gpg"] ?? []

        var byTime: [Date: Snapshot] = [:]
        var failures = 0
        var nonComparable = 0
        for start in stride(from: 0, to: paths.count, by: 8) {
            let batch = paths[start..<min(start + 8, paths.count)]
            await withTaskGroup(of: Snapshot?.self) { group in
                for path in batch {
                    group.addTask { try? await read(path: path, gpg: gpg) }
                }
                for await snapshot in group {
                    guard let snapshot else { failures += 1; continue }
                    guard snapshot.users != nil else { nonComparable += 1; continue }
                    if byTime[snapshot.collectedAt]?.changes == nil {
                        byTime[snapshot.collectedAt] = snapshot
                    }
                }
            }
        }

        // The latest pointer can advance between the directory lookup and the bulk fetch.
        do {
            let latest: Snapshot = try await read(path: "latest-stargazers.json.gpg", gpg: gpg)
            if latest.users != nil { byTime[latest.collectedAt] = latest }
        } catch {
            guard !byTime.isEmpty else { throw error }
        }
        guard !byTime.isEmpty else { throw RosterError.noHistory }
        return Roster(snapshots: byTime.values.sorted { $0.collectedAt < $1.collectedAt },
                      unavailable: failures, nonComparable: nonComparable)
    }

    func recordedPaths(_ filenames: [String]) async throws -> [String: [String]] {
        let treeURL = URL(string: api.absoluteString + "/git/trees/project-metrics?recursive=1")!
        let treeData: Data
        do {
            treeData = try await fetch(treeURL)
        } catch RosterError.rateLimit {
            treeData = try authenticatedTree()
        }
        let tree = try JSONDecoder().decode(Tree.self, from: treeData)
        guard !tree.truncated else { throw RosterError.invalidTree }
        let candidates = tree.tree.filter {
            $0.type == "blob" && $0.path.range(of: #"^runs/[0-9]+/[0-9]+/[^/]+$"#,
                                              options: .regularExpression) != nil
        }.map(\.path)
        return Dictionary(grouping: candidates.filter { path in
            filenames.contains(String(path.split(separator: "/").last ?? ""))
        }) { String($0.split(separator: "/").last ?? "") }
    }

    func publicRun(path: String) async throws -> Data {
        try await fetch(raw.appendingPathComponent(path))
    }

    func encryptedForkRun(path: String) async throws -> ForkSample {
        guard FileManager.default.isReadableFile(atPath: key.path) else { throw RosterError.noKey }
        guard let gpg = ["/opt/homebrew/bin/gpg", "/usr/local/bin/gpg", "/usr/local/MacGPG2/bin/gpg"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { throw RosterError.noGPG }
        return try await read(path: path, gpg: gpg)
    }

    private func authenticatedTree() throws -> Data {
        guard let gh = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw RosterError.rateLimit
        }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: gh)
        process.arguments = ["api", "repos/CHNragdoll/anki-pipeline/git/trees/project-metrics?recursive=1"]
        var environment = ProcessInfo.processInfo.environment
        environment["GH_PROMPT_DISABLED"] = "1"
        process.environment = environment
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw RosterError.rateLimit }
        return data
    }

    private func fetch(_ url: URL) async throws -> Data {
        let (data, response) = try await session.data(from: url)
        guard let response = response as? HTTPURLResponse else { throw RosterError.invalidResponse }
        if response.statusCode == 429 || response.value(forHTTPHeaderField: "x-ratelimit-remaining") == "0"
            && response.statusCode == 403 { throw RosterError.rateLimit }
        guard response.statusCode == 200 else { throw RosterError.invalidResponse }
        return data
    }

    func readBatch<Value>(_ paths: [String], load: @escaping (String) async throws -> Value) async -> [Value] {
        var results: [Value] = []
        for start in stride(from: 0, to: paths.count, by: 8) {
            guard !Task.isCancelled else { break }
            let batch = paths[start..<min(start + 8, paths.count)]
            await withTaskGroup(of: Value?.self) { group in
                for path in batch { group.addTask { try? await load(path) } }
                for await result in group { if let result { results.append(result) } }
            }
        }
        return results
    }

    func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    private func read<Entry: Decodable>(path: String, gpg: String) async throws -> Entry {
        let encrypted = try await fetch(raw.appendingPathComponent(path))
        let process = Process()
        let input = Pipe()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: gpg)
        process.arguments = ["--quiet", "--batch", "--no-tty", "--pinentry-mode", "loopback",
                             "--passphrase-file", key.path, "--decrypt"]
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        DispatchQueue.global(qos: .utility).async {
            defer { try? input.fileHandleForWriting.close() }
            try? input.fileHandleForWriting.write(contentsOf: encrypted)
        }
        let plaintext = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw RosterError.decrypt }
        return try decoder().decode(Entry.self, from: plaintext)
    }
}
