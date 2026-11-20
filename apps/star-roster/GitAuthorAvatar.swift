import SwiftUI

private actor CommitAttribution {
    static let shared = CommitAttribution()
    private var requests: [String: Task<Int64?, Never>] = [:]

    func id(for sha: String) async -> Int64? {
        if let known = requests[sha] { return await known.value }
        let request = Task { await Self.fetchID(sha) }
        requests[sha] = request
        return await request.value
    }

    private static func fetchID(_ sha: String) async -> Int64? {
        struct Response: Decodable {
            struct Author: Decodable { let id: Int64 }
            let author: Author?
        }
        guard let url = URL(string: "https://api.github.com/repos/CHNragdoll/anki-pipeline/commits/\(sha)") else { return nil }
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 10
        let session = URLSession(configuration: config)
        if let (data, response) = try? await session.data(from: url) {
            let code = (response as? HTTPURLResponse)?.statusCode
            if code == 200 { return (try? JSONDecoder().decode(Response.self, from: data))?.author?.id }
            if code != 403 && code != 429 { return nil }
        }
        guard let gh = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"].first(where: FileManager.default.isExecutableFile(atPath:))
        else { return nil }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: gh)
        process.arguments = ["api", "repos/CHNragdoll/anki-pipeline/commits/\(sha)", "--jq", ".author.id"]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        guard (try? process.run()) != nil else { return nil }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        return Int64(String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

@MainActor
private final class CommitAvatarModel: ObservableObject {
    @Published var image: NSImage?
    @Published var id: Int64?

    func load(_ commit: GitCommit) async {
        var id = commit.avatarID
        if id == nil, let sha = commit.avatarCommit { id = await CommitAttribution.shared.id(for: sha) }
        guard !Task.isCancelled, let id, let url = URL(string: "https://avatars.githubusercontent.com/u/\(id)?s=80&v=4")
        else { return }
        self.id = id
        let loaded = await AvatarLoader.shared.image(at: url)
        if !Task.isCancelled { image = loaded }
    }
}

struct GitAuthorAvatar: View {
    let commit: GitCommit
    var size: CGFloat = 27
    var interactive = false
    @StateObject private var model = CommitAvatarModel()

    var body: some View {
        Group {
            if interactive, let id = model.id {
                AvatarView(star: Star(id: id, login: commit.author, starredAt: nil))
            } else if let image = model.image {
                Image(nsImage: image).resizable().scaledToFill()
                    .accessibilityLabel("GitHub 作者头像")
            } else {
                Circle().fill(Color.accentColor.opacity(0.12)).overlay {
                    if commit.author.hasSuffix("[bot]") {
                        Image(systemName: "gearshape").font(.system(size: 11))
                    } else {
                        Text(String(commit.author.prefix(1)).uppercased()).font(.caption.weight(.semibold))
                    }
                }
                .foregroundStyle(Color.accentColor)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .task(id: commit.id) { await model.load(commit) }
    }
}
