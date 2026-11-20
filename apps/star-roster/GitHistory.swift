import Foundation

struct GitCommit: Identifiable {
    let id: String
    let parents: [String]
    let author: String
    let date: Date
    let refs: [String]
    let title: String
    var avatarID: Int64? = nil
    var avatarCommit: String? = nil

    var shortID: String { String(id.prefix(7)) }
    var isMerge: Bool { parents.count > 1 }

    var relatedLink: GitCommitLink? {
        let parts = title.split(separator: " ")
        if parts.count > 3, parts[0] == "Merge", parts[1] == "pull", parts[2] == "request",
           parts[3].hasPrefix("#"), let number = Int64(parts[3].dropFirst()), number > 0 {
            return GitCommitLink(title: "PR #\(number)", symbol: "arrow.triangle.merge", path: "pull/\(number)")
        }
        if parts.count >= 7, title.hasPrefix("chore: archive project metrics run "),
           let run = Int64(parts[5]), run > 0 {
            return GitCommitLink(title: "Action 运行", symbol: "play.circle", path: "actions/runs/\(run)")
        }
        return nil
    }
}

struct GitCommitLink {
    let title: String
    let symbol: String
    let path: String

    var url: URL { URL(string: "https://github.com/CHNragdoll/anki-pipeline/\(path)")! }
}

enum GitScope: String, CaseIterable, Identifiable {
    case overview = "全部"
    case main = "main"
    case metrics = "project-metrics"
    case worktree = "当前分支"

    var id: Self { self }

    var refs: [String] {
        switch self {
        case .overview: ["HEAD", "refs/remotes/origin/main", "refs/remotes/origin/project-metrics"]
        case .main: ["refs/remotes/origin/main"]
        case .metrics: ["refs/remotes/origin/project-metrics"]
        case .worktree: ["HEAD"]
        }
    }
}

enum GitChangeGroup: String, CaseIterable, Identifiable {
    case staged = "已暂存"
    case unstaged = "未暂存"
    case untracked = "未跟踪"
    var id: Self { self }
}

struct GitWorktree {
    let branch: String
    let files: [GitChangeGroup: [GitChangedFile]]

    var staged: Int { files[.staged]?.count ?? 0 }
    var unstaged: Int { files[.unstaged]?.count ?? 0 }
    var untracked: Int { files[.untracked]?.count ?? 0 }
    var hasChanges: Bool { staged + unstaged + untracked > 0 }

    init(branch: String, status: Data) {
        self.branch = branch
        let fields = status.split(separator: 0)
        var files: [GitChangeGroup: [GitChangedFile]] = [:]
        var index = 0
        while index < fields.count {
            let field = fields[index]
            index += 1
            guard field.count >= 3 else { continue }
            let codes = Array(field.prefix(2))
            let path = String(decoding: field.dropFirst(3), as: UTF8.self)
            var oldPath: String?
            if codes.contains(82) || codes.contains(67), index < fields.count {
                oldPath = String(decoding: fields[index], as: UTF8.self)
                index += 1
            }
            if codes == [63, 63] {
                files[.untracked, default: []].append(.init(path: path, oldPath: nil, status: "?"))
            } else {
                for (group, code) in [(GitChangeGroup.staged, codes[0]), (.unstaged, codes[1])] where code != 32 {
                    let prior = code == 82 || code == 67 ? oldPath : nil
                    files[group, default: []].append(.init(path: path, oldPath: prior, status: String(UnicodeScalar(code))))
                }
            }
        }
        self.files = files
    }
}

struct GitHistoryResult {
    let rows: [GitGraphRow]
    let worktree: GitWorktree
    let hasMore: Bool
}

struct GitRef: Identifiable, Equatable {
    let id: String
    let name: String

    var group: String {
        if id.hasPrefix("refs/heads/") { return "本地分支" }
        if id.hasPrefix("refs/remotes/") { return "远端跟踪分支" }
        return "标签"
    }
}

struct GitChangedFile: Identifiable, Equatable {
    let path: String
    let oldPath: String?
    let status: String
    var id: String { path }
}

struct GitFileDiff {
    let lines: [String]
    let truncated: Bool
}

struct GitCommitDetails {
    let body: String
    let publicURL: URL?
    let files: [GitChangedFile]
}

struct GitRepository {
    private let directory: URL?

    init(directory: URL? = GitRepository.checkoutDirectory()) {
        self.directory = directory
    }

    static func checkoutDirectory(bundleURL: URL = Bundle.main.bundleURL,
                                  preference: String? = UserDefaults.standard.string(forKey: "repositoryPath")) -> URL? {
        let candidate: URL
        if let preference, !preference.isEmpty {
            candidate = URL(fileURLWithPath: (preference as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            // The default build puts the app in <checkout>/apps/star-roster/.
            let sourceDirectory = bundleURL.deletingLastPathComponent()
            let appsDirectory = sourceDirectory.deletingLastPathComponent()
            guard sourceDirectory.lastPathComponent == "star-roster", appsDirectory.lastPathComponent == "apps" else {
                return nil
            }
            candidate = appsDirectory.deletingLastPathComponent()
        }
        let files = FileManager.default
        guard files.fileExists(atPath: candidate.appendingPathComponent(".git").path),
              files.fileExists(atPath: candidate.appendingPathComponent("scripts/project_metrics.py").path) else { return nil }
        return candidate.standardizedFileURL
    }

    func fetchOrigin() async throws {
        var environment = ProcessInfo.processInfo.environment
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_HTTP_LOW_SPEED_LIMIT"] = "1"
        environment["GIT_HTTP_LOW_SPEED_TIME"] = "20"
        _ = try git(["fetch", "--atomic", "--no-auto-maintenance", "--no-recurse-submodules",
                     "--no-tags", "--no-prune", "--no-prune-tags", "--no-write-fetch-head", "--refmap=",
                     "origin", "+refs/heads/*:refs/remotes/origin/*"], environment: environment)
    }

    func history(scope: GitScope, ref: GitRef? = nil, query: String = "", limit: Int) async throws -> GitHistoryResult {
        let format = "%H%x00%P%x00%an%x00%at%x00%D%x00%s%x00%ae"
        let terms = query.split(whereSeparator: \.isWhitespace).map(String.init)
        let refs: [String]
        if let ref {
            refs = [ref.id]
        } else if scope == .overview {
            // A shallow or single-branch checkout may lack the data branch before its first refresh.
            let trackingRefs = scope.refs.filter { $0 != "HEAD" }
            let available = try string(["for-each-ref", "--format=%(refname)"] + trackingRefs)
            let names = Set(available.split(separator: "\n").map(String.init))
            refs = ["HEAD"] + trackingRefs.filter { names.contains($0) }
        } else {
            refs = scope.refs
        }
        var arguments = ["log", "-z", "--date-order", "--decorate=short", "--format=\(format)"]
        if terms.isEmpty { arguments.append("--max-count=\(limit + 1)") }
        let raw = try git(arguments + refs + ["--"])
        let fields = raw.split(separator: 0, omittingEmptySubsequences: false).dropLast()
        let values = fields.map { String(decoding: $0, as: UTF8.self) }
        let identities = stride(from: 0, to: values.count, by: 7).compactMap {
            $0 + 6 < values.count ? values[$0 + 6] : nil
        }
        let missing = Set(identities.filter { !$0.isEmpty && Self.avatarID(email: $0) == nil })
        let publicCandidates = missing.isEmpty ? [:] : (try? publicAvatarCandidates(for: missing)) ?? [:]
        let commits: [GitCommit] = stride(from: 0, to: values.count, by: 7).compactMap { index in
            guard index + 6 < values.count, let timestamp = Double(values[index + 3]) else { return nil }
            return GitCommit(id: values[index], parents: values[index + 1].split(separator: " ").map(String.init),
                             author: values[index + 2], date: Date(timeIntervalSince1970: timestamp),
                             refs: values[index + 4].components(separatedBy: ", ").filter { !$0.isEmpty },
                             title: values[index + 5], avatarID: Self.avatarID(email: values[index + 6]),
                             avatarCommit: publicCandidates[values[index + 6]])
        }
        let filtered = terms.isEmpty ? commits : commits.filter { commit in
            let searchable = [commit.id, commit.author, commit.title] + commit.refs
            return terms.allSatisfy { term in searchable.contains { $0.localizedCaseInsensitiveContains(term) } }
        }
        let shown = Array(filtered.prefix(limit))
        let rows = terms.isEmpty ? GitGraph.layout(shown) : shown.map {
            GitGraphRow(commit: $0, lane: 0, color: 0, laneCount: 1, edges: [])
        }
        let branch = try string(["rev-parse", "--abbrev-ref", "HEAD"])
        let status = try git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"])
        return GitHistoryResult(rows: rows,
                                worktree: GitWorktree(branch: branch, status: status),
                                hasMore: filtered.count > limit)
    }

    private static func avatarID(email: String) -> Int64? {
        let suffix = "@users.noreply.github.com"
        guard email.hasSuffix(suffix) else { return nil }
        let prefix = email.dropLast(suffix.count)
        guard let split = prefix.firstIndex(of: "+"), let number = Int64(prefix[..<split]), number > 0 else { return nil }
        return number
    }

    private func publicAvatarCandidates(for emails: Set<String>) throws -> [String: String] {
        let raw = try git(["log", "-z", "--format=%H%x00%ae", "refs/remotes/origin/main",
                           "refs/remotes/origin/project-metrics", "--"])
        let values = raw.split(separator: 0, omittingEmptySubsequences: false).map { String(decoding: $0, as: UTF8.self) }
        var candidates: [String: String] = [:]
        for index in stride(from: 0, to: values.count - 1, by: 2) {
            let email = values[index + 1]
            if emails.contains(email) && candidates[email] == nil { candidates[email] = values[index] }
        }
        return candidates
    }

    func references() async throws -> [GitRef] {
        let raw = try string(["for-each-ref", "--sort=refname", "--format=%(refname)%00%(refname:short)",
                              "refs/heads", "refs/remotes", "refs/tags"])
        return raw.split(separator: "\n").compactMap {
            let parts = $0.split(separator: "\0")
            guard parts.count == 2, !parts[0].hasSuffix("/HEAD") else { return nil }
            return GitRef(id: String(parts[0]), name: String(parts[1]))
        }
    }

    func details(for commit: GitCommit) async throws -> GitCommitDetails {
        let description = try string(["show", "--no-patch", "--format=%b", commit.id, "--"])
        let remoteRefs = try string(["for-each-ref", "--contains=\(commit.id)", "--format=%(refname)",
                                     "refs/remotes/origin"])
        let url = remoteRefs.isEmpty ? nil : URL(string: "https://github.com/CHNragdoll/anki-pipeline/commit/\(commit.id)")
        let fields = try git(["diff-tree", "--no-commit-id", "--root", "-r", "-z", "--name-status", "-M"]
                             + comparison(for: commit) + ["--"])
            .split(separator: 0).map { String(decoding: $0, as: UTF8.self) }
        var files: [GitChangedFile] = []
        var index = 0
        while index + 1 < fields.count {
            let status = String(fields[index].prefix(1))
            let hasOldPath = status == "R" || status == "C"
            guard !hasOldPath || index + 2 < fields.count else { break }
            files.append(GitChangedFile(path: fields[index + (hasOldPath ? 2 : 1)],
                                        oldPath: hasOldPath ? fields[index + 1] : nil, status: status))
            index += hasOldPath ? 3 : 2
        }
        return GitCommitDetails(body: description, publicURL: url, files: files)
    }

    func diff(for commit: GitCommit, file: GitChangedFile) async throws -> GitFileDiff {
        try patch(["diff-tree", "--no-commit-id", "--root", "-r", "-p", "-M"] + comparison(for: commit), file: file)
    }

    func worktreeDiff(for file: GitChangedFile, group: GitChangeGroup) async throws -> GitFileDiff {
        try patch(group == .staged ? ["diff", "--cached"] : ["diff"], file: file)
    }

    private func patch(_ arguments: [String], file: GitChangedFile) throws -> GitFileDiff {
        let paths = [file.oldPath, file.path].compactMap { $0 }
        let patchArgs = ["--literal-pathspecs"] + arguments + ["--no-color", "--no-ext-diff", "--no-textconv"]
        let maxBytes = 512 * 1024
        let raw = try git(patchArgs + ["--"] + paths, byteLimit: maxBytes)
        let lines = raw.isEmpty ? [] : String(decoding: raw, as: UTF8.self).components(separatedBy: "\n")
        return GitFileDiff(lines: Array(lines.prefix(1500)), truncated: raw.count > maxBytes || lines.count > 1500)
    }

    private func comparison(for commit: GitCommit) -> [String] {
        [commit.parents.first, commit.id].compactMap { $0 }
    }

    private func string(_ arguments: [String]) throws -> String {
        try String(decoding: git(arguments), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func git(_ arguments: [String], byteLimit: Int? = nil, environment: [String: String]? = nil) throws -> Data {
        guard let directory else { throw GitCheckoutUnavailable() }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        process.arguments = ["--no-optional-locks", "-C", directory.path] + arguments
        process.environment = environment
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let handle = output.fileHandleForReading
        let result: Data
        if let byteLimit {
            var captured = Data()
            while captured.count <= byteLimit,
                  let bytes = try handle.read(upToCount: min(65_536, byteLimit + 1 - captured.count)),
                  !bytes.isEmpty {
                captured.append(bytes)
            }
            result = captured
            if result.count > byteLimit {
                try handle.close()
                process.waitUntilExit()
                return result
            }
        } else {
            result = handle.readDataToEndOfFile()
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw GitFailure() }
        return result
    }

    private struct GitFailure: Error {}
}

struct GitCheckoutUnavailable: LocalizedError {
    var errorDescription: String? { "找不到 anki-pipeline 本地检出。请按构建说明配置 repositoryPath。" }
}

struct GitGraphRow: Identifiable {
    struct Edge {
        let from: Int
        let to: Int
        let color: Int
        let start: Double
        let stop: Double
    }

    let commit: GitCommit
    let lane: Int
    let color: Int
    let laneCount: Int
    let edges: [Edge]
    var id: String { commit.id }
}

enum GitGraph {
    private struct Lane {
        var next: String
        let color: Int
    }

    static func layout(_ commits: [GitCommit]) -> [GitGraphRow] {
        var active: [Lane] = []
        var nextColor = 0
        func lane(for id: String) -> Lane {
            defer { nextColor += 1 }
            return Lane(next: id, color: nextColor)
        }

        return commits.map { commit in
            let before = active
            let incoming = before.firstIndex { $0.next == commit.id }
            if incoming == nil { active.append(lane(for: commit.id)) }
            let node = incoming ?? active.count - 1
            let color = active[node].color
            active.remove(at: node)

            for (index, parent) in commit.parents.enumerated() {
                if active.contains(where: { $0.next == parent }) { continue }
                if index == 0 {
                    active.insert(Lane(next: parent, color: color), at: node)
                } else {
                    active.insert(lane(for: parent), at: min(node + index, active.count))
                }
            }

            var edges: [GitGraphRow.Edge] = []
            for (index, previous) in before.enumerated() where previous.next != commit.id {
                if let target = active.firstIndex(where: { $0.next == previous.next }) {
                    edges.append(.init(from: index, to: target, color: previous.color, start: 0, stop: 1))
                }
            }
            if let incoming {
                edges.append(.init(from: incoming, to: node, color: color, start: 0, stop: 0.5))
            }
            for parent in commit.parents {
                if let target = active.firstIndex(where: { $0.next == parent }) {
                    edges.append(.init(from: node, to: target, color: active[target].color, start: 0.5, stop: 1))
                }
            }
            return GitGraphRow(commit: commit, lane: node, color: color,
                               laneCount: max(before.count, active.count, node + 1), edges: edges)
        }
    }
}
