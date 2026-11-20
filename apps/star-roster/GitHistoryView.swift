import SwiftUI

@MainActor
private final class GitHistoryModel: ObservableObject {
    @Published var scope = GitScope.overview
    @Published var limit = 140
    @Published var query = ""
    @Published var selectedRef: GitRef?
    @Published var refs: [GitRef] = []
    @Published var history: GitHistoryResult?
    @Published var error: String?
    @Published private(set) var syncing = false
    @Published private(set) var syncFailed = false
    @Published var selection: GitCommit?
    @Published var showWorktree = false
    private let repository = GitRepository()
    private var sync: (id: Int, task: Task<Bool, Never>)?
    private var loadedRefsID: Int?

    func load(refreshID: Int) async {
        do {
            try Task.checkCancellation()
            if refreshID > 0 { try await syncOrigin(refreshID: refreshID) }
            if loadedRefsID != refreshID, let available = try? await repository.references() {
                try Task.checkCancellation()
                refs = available
                loadedRefsID = refreshID
            }
            if !query.isEmpty { try await Task.sleep(for: .milliseconds(220)) }
            let latest = try await repository.history(scope: scope, ref: selectedRef, query: query, limit: limit)
            guard !Task.isCancelled else { return }
            history = latest
            error = nil
        } catch {
            guard !Task.isCancelled else { return }
            self.error = (error as? GitCheckoutUnavailable)?.errorDescription ?? "无法读取本地 anki-pipeline 的 Git 历史。"
        }
    }

    private func syncOrigin(refreshID: Int) async throws {
        if sync?.id != refreshID {
            let previous = sync?.task
            let task = Task { [repository] in
                _ = await previous?.value
                do {
                    try await repository.fetchOrigin()
                    return true
                } catch {
                    return false
                }
            }
            sync = (refreshID, task)
            syncing = true
            syncFailed = false
        }
        if let success = await sync?.task.value {
            try Task.checkCancellation()
            guard sync?.id == refreshID else { throw CancellationError() }
            syncing = false
            syncFailed = !success
        }
    }
}

struct GitHistoryView: View {
    let refreshID: Int
    @StateObject private var model = GitHistoryModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            if let error = model.error {
                ContentUnavailableView("Git 记录暂不可用", systemImage: "arrow.triangle.branch",
                                       description: Text(error))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let history = model.history {
                historyList(history)
            } else {
                ProgressView("正在读取 Git 历史…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: Request(scope: model.scope, ref: model.selectedRef, query: model.query, limit: model.limit, refreshID: refreshID)) {
            await model.load(refreshID: refreshID)
        }
        .sheet(item: $model.selection) { CommitInspector(commit: $0) }
        .sheet(isPresented: $model.showWorktree) {
            if let tree = model.history?.worktree { GitWorktreeInspector(tree: tree) }
        }
    }

    private struct Request: Equatable {
        let scope: GitScope
        let ref: GitRef?
        let query: String
        let limit: Int
        let refreshID: Int
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Git 记录", systemImage: "arrow.triangle.branch")
                    .font(.title2.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                if let history = model.history, model.error == nil {
                    Text("\(history.rows.count) 条提交").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            Text("本地 anki-pipeline · 北京时间")
                .font(.caption).foregroundStyle(.secondary)
            if model.syncing {
                Text("正在同步远端分支…")
                    .font(.caption).foregroundStyle(.secondary)
            } else if model.syncFailed {
                Text("远端分支同步失败，当前显示本机 Git 记录。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            scopeSelector
            HStack(spacing: 8) {
                referenceMenu
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("搜索标题、作者或 SHA", text: $model.query)
                        .textFieldStyle(.plain)
                        .accessibilityIdentifier("git-commit-search")
                    if !model.query.isEmpty {
                        Button { model.query = "" } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("清空搜索")
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                .frame(maxWidth: 350)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 15)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private var referenceMenu: some View {
        Menu {
            ForEach(["本地分支", "远端跟踪分支", "标签"], id: \.self) { group in
                Menu(group) {
                    ForEach(model.refs.filter { $0.group == group }) { ref in
                        Button(ref.name) {
                            model.selectedRef = ref
                            model.limit = 140
                        }
                    }
                }
            }
        } label: {
            Label(model.selectedRef?.name ?? "分支与标签", systemImage: "arrow.triangle.branch")
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: 165)
        .accessibilityIdentifier("git-reference-menu")
    }

    private var scopeSelector: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 4) {
                ForEach(GitScope.allCases) { scope in
                    let selected = model.scope == scope && model.selectedRef == nil
                    Button {
                        model.scope = scope
                        model.selectedRef = nil
                        model.limit = 140
                    } label: {
                        Text(scope.rawValue)
                            .font(.subheadline.weight(selected ? .semibold : .regular))
                            .foregroundStyle(selected ? Color.white : Color.primary)
                            .padding(.horizontal, 11)
                            .frame(height: 25)
                            .background {
                                if selected {
                                    RoundedRectangle(cornerRadius: 5).fill(Color.accentColor)
                                }
                            }
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .handCursor()
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .accessibilityIdentifier("git-scope-\(scope)")
                }
            }
            .fixedSize(horizontal: true, vertical: false)
            .padding(3)
            .background(.quaternary.opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
        }
        .scrollIndicators(.hidden)
        .clipped()
        .accessibilityLabel("提交范围")
    }

    private func historyList(_ history: GitHistoryResult) -> some View {
        if history.rows.isEmpty {
            return AnyView(ContentUnavailableView("没有匹配的提交", systemImage: "magnifyingglass")
                .frame(maxWidth: .infinity, maxHeight: .infinity))
        }
        let lanes = history.rows.map(\.laneCount).max() ?? 1
        let width = max(54, min(174, 24 + CGFloat(lanes) * 15))
        return AnyView(ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                if model.query.isEmpty && model.selectedRef == nil && (model.scope == .overview || model.scope == .worktree) {
                    worktreeRow(history.worktree)
                }
                ForEach(history.rows) { row in
                    commitRow(row, lanes: lanes, width: width)
                }
                if history.hasMore {
                    Button("加载更早的提交") { model.limit += 140 }
                        .handCursor()
                        .frame(maxWidth: .infinity)
                        .padding(16)
                }
            }
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10).strokeBorder(.quaternary, lineWidth: 1)
                    .allowsHitTesting(false)
            }
            .padding(14)
            .frame(maxWidth: 1040)
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("git-history-list"))
    }

    private func worktreeRow(_ tree: GitWorktree) -> some View {
        Button {
            model.showWorktree = true
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 7) {
                        Label("工作区", systemImage: "laptopcomputer").font(.subheadline.weight(.semibold))
                        Text(tree.branch).lineLimit(1).truncationMode(.middle)
                            .font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                    Text(tree.hasChanges
                         ? "已暂存 \(tree.staged) · 未暂存 \(tree.unstaged) · 未跟踪 \(tree.untracked)"
                         : "工作区干净")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
                Spacer()
                Label("查看文件", systemImage: "chevron.right")
                    .labelStyle(.iconOnly)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.07))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .handCursor()
        .accessibilityIdentifier("git-worktree")
    }

    private func commitRow(_ row: GitGraphRow, lanes: Int, width: CGFloat) -> some View {
        let commit = row.commit
        return Button {
            model.selection = commit
        } label: {
            HStack(spacing: 0) {
                CommitLines(row: row, lanes: lanes)
                    .frame(width: width)
                    .accessibilityHidden(true)
                GitAuthorAvatar(commit: commit)
                    .padding(.trailing, 9)
                VStack(alignment: .leading, spacing: 4) {
                    Text(commit.title)
                        .font(.subheadline.weight(commit.isMerge ? .semibold : .medium))
                        .lineLimit(1)
                        .truncationMode(.tail)
                    HStack(spacing: 7) {
                        ForEach(Array(commit.refs.prefix(2)), id: \.self) { ref in
                            Text(ref)
                                .font(.caption2.weight(.semibold))
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .foregroundStyle(GitColors.color(row.color))
                                .background(GitColors.color(row.color).opacity(0.10), in: RoundedRectangle(cornerRadius: 4))
                                .frame(maxWidth: 125)
                                .layoutPriority(-1)
                        }
                        Text(commit.shortID).font(.caption.monospaced())
                        Text(commit.author).lineLimit(1)
                        if let related = commit.relatedLink {
                            Text(related.title)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(Color.accentColor)
                                .lineLimit(1)
                                .fixedSize()
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Text(String(ProjectMetrics.fullTime(commit.date).dropFirst(5).prefix(11)))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .fixedSize()
                    .padding(.trailing, 12)
            }
            .frame(height: 48)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .overlay(alignment: .bottom) {
                Divider().padding(.leading, width)
            }
            .background {
                if commit.isMerge { GitColors.color(row.color).opacity(0.05) }
            }
        }
        .buttonStyle(.plain)
        .handCursor()
        .help("\(commit.title) · \(ProjectMetrics.fullTime(commit.date))")
        .accessibilityIdentifier("git-commit-\(commit.shortID)")
        .contextMenu {
            Button("查看提交详情") { model.selection = commit }
            Button("复制 SHA") { copyGitText(commit.id) }
            if let related = commit.relatedLink {
                Button("打开 \(related.title)") { NSWorkspace.shared.open(related.url) }
            }
        }
    }
}

private enum GitColors {
    static func color(_ index: Int) -> Color {
        let palette: [Color] = [.blue, .purple, .teal, .orange, .indigo, .pink, .mint, .cyan]
        return palette[index % palette.count]
    }
}

private struct CommitLines: View {
    let row: GitGraphRow
    let lanes: Int

    var body: some View {
        Canvas { context, size in
            let gap = min(15, (size.width - 24) / CGFloat(max(1, lanes - 1)))
            func x(_ index: Int) -> CGFloat { 13 + CGFloat(index) * gap }

            for edge in row.edges {
                let start = CGPoint(x: x(edge.from), y: size.height * edge.start)
                let end = CGPoint(x: x(edge.to), y: size.height * edge.stop)
                let mid = (start.y + end.y) / 2
                let line = Path { path in
                    path.move(to: start)
                    path.addCurve(to: end, control1: CGPoint(x: start.x, y: mid),
                                  control2: CGPoint(x: end.x, y: mid))
                }
                context.stroke(line, with: .color(GitColors.color(edge.color).opacity(0.80)),
                               style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            let node = CGPoint(x: x(row.lane), y: size.height / 2)
            let radius: CGFloat = row.commit.isMerge ? 5 : 3.7
            let dot = Path(ellipseIn: CGRect(x: node.x - radius, y: node.y - radius,
                                             width: radius * 2, height: radius * 2))
            let color = GitColors.color(row.color)
            context.fill(dot, with: .color(row.commit.isMerge ? Color(nsColor: .controlBackgroundColor) : color))
            if row.commit.isMerge { context.stroke(dot, with: .color(color), lineWidth: 2) }
        }
    }
}

@MainActor
private final class CommitInspectorModel: ObservableObject {
    @Published var details: GitCommitDetails?
    @Published var failed = false
    @Published var selectedFile: GitChangedFile?
    @Published var fileDiff: GitFileDiff?
    @Published var diffFailed = false

    func load(_ commit: GitCommit) async {
        do {
            let loaded = try await GitRepository().details(for: commit)
            details = loaded
            selectedFile = loaded.files.first
        } catch { failed = true }
    }

    func loadDiff(_ commit: GitCommit) async {
        fileDiff = nil
        diffFailed = false
        guard let file = selectedFile else { return }
        do {
            let loaded = try await GitRepository().diff(for: commit, file: file)
            guard !Task.isCancelled else { return }
            fileDiff = loaded
        } catch {
            if !Task.isCancelled { diffFailed = true }
        }
    }
}

private struct CommitInspector: View {
    let commit: GitCommit
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = CommitInspectorModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack(alignment: .top) {
                Text(commit.title).font(.headline).textSelection(.enabled)
                Spacer()
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            HStack(spacing: 8) {
                GitAuthorAvatar(commit: commit, size: 32, interactive: true)
                Text("\(commit.author) · \(ProjectMetrics.fullTime(commit.date))")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            HStack {
                Text(commit.id).font(.caption.monospaced()).textSelection(.enabled)
                Button("复制 SHA") { copyGitText(commit.id) }
            }
            if !commit.refs.isEmpty {
                Text(commit.refs.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            }
            if !commit.parents.isEmpty {
                Text("父提交  \(commit.parents.map { String($0.prefix(7)) }.joined(separator: "  "))")
                    .font(.caption.monospaced()).foregroundStyle(.secondary)
            }
            if let details = model.details {
                if !details.body.isEmpty {
                    ScrollView {
                        Text(details.body).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 75)
                }
                HStack(spacing: 14) {
                    if let url = details.publicURL {
                        Link("在 GitHub 查看提交", destination: url).handCursor()
                    }
                    if let related = commit.relatedLink {
                        Link(destination: related.url) { Label(related.title, systemImage: related.symbol) }
                            .handCursor()
                    }
                }
                changes(details.files)
            } else if model.failed {
                Text("暂时无法读取提交详情。").foregroundStyle(.secondary)
            }
        }
        .padding(20)
        .frame(width: 620)
        .task { await model.load(commit) }
        .task(id: model.selectedFile) { await model.loadDiff(commit) }
    }

    private func changes(_ files: [GitChangedFile]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Divider()
            HStack {
                Text("\(files.count) 个改动文件").font(.subheadline.weight(.semibold))
                Spacer()
                if commit.isMerge { Text("与第一父提交比较").font(.caption).foregroundStyle(.secondary) }
            }
            if files.isEmpty {
                Text("此提交没有文件变化。").font(.caption).foregroundStyle(.secondary)
            } else {
                GitChangesPanel(files: files, selection: $model.selectedFile, diff: model.fileDiff,
                                failed: model.diffFailed, untracked: false)
            }
        }
    }

}

private func copyGitText(_ value: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(value, forType: .string)
}

@MainActor
private final class GitWorktreeModel: ObservableObject {
    @Published var group = GitChangeGroup.unstaged
    @Published var file: GitChangedFile?
    @Published var diff: GitFileDiff?
    @Published var failed = false

    func read() async {
        diff = nil
        failed = false
        guard group != .untracked, let file else { return }
        do {
            let result = try await GitRepository().worktreeDiff(for: file, group: group)
            if !Task.isCancelled { diff = result }
        } catch {
            if !Task.isCancelled { failed = true }
        }
    }
}

private struct GitWorktreeInspector: View {
    let tree: GitWorktree
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = GitWorktreeModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("工作区文件", systemImage: "laptopcomputer").font(.headline)
                Spacer()
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            Text(tree.branch).font(.caption.monospaced()).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                ForEach(GitChangeGroup.allCases) { group in
                    Button {
                        model.group = group
                        model.file = tree.files[group]?.first
                    } label: {
                        Text("\(group.rawValue) \(tree.files[group]?.count ?? 0)")
                            .font(.subheadline.monospacedDigit())
                    }
                    .buttonStyle(.bordered)
                    .tint(model.group == group ? .accentColor : .secondary)
                    .accessibilityAddTraits(model.group == group ? .isSelected : [])
                    .accessibilityIdentifier("git-worktree-\(group)")
                }
            }
            GitChangesPanel(files: tree.files[model.group] ?? [], selection: $model.file, diff: model.diff,
                            failed: model.failed, untracked: model.group == .untracked)
        }
        .padding(20)
        .frame(width: 620)
        .onAppear {
            model.group = [.unstaged, .staged, .untracked].first { !(tree.files[$0]?.isEmpty ?? true) } ?? .unstaged
            model.file = tree.files[model.group]?.first
        }
        .task(id: Selection(group: model.group, file: model.file)) { await model.read() }
    }

    private struct Selection: Equatable {
        let group: GitChangeGroup
        let file: GitChangedFile?
    }
}

private struct GitChangesPanel: View {
    let files: [GitChangedFile]
    @Binding var selection: GitChangedFile?
    let diff: GitFileDiff?
    let failed: Bool
    let untracked: Bool

    var body: some View {
        if files.isEmpty {
            ContentUnavailableView("没有文件", systemImage: "checkmark.circle")
                .frame(height: 150)
                .frame(maxWidth: .infinity)
        } else {
            HStack(spacing: 0) {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        ForEach(files) { file in
                            Button { selection = file } label: {
                                HStack(spacing: 6) {
                                    Text(file.status)
                                        .font(.caption.monospaced().weight(.semibold))
                                        .foregroundStyle(statusColor(file.status))
                                        .frame(width: 10)
                                    Text(file.path).lineLimit(1).truncationMode(.middle).font(.caption)
                                    Spacer(minLength: 0)
                                }
                                .padding(6)
                                .background(selection == file ? Color.accentColor.opacity(0.15) : .clear,
                                            in: RoundedRectangle(cornerRadius: 5))
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .handCursor()
                            .help(file.oldPath.map { "\($0) → \(file.path)" } ?? file.path)
                            .accessibilityAddTraits(selection == file ? .isSelected : [])
                            .contextMenu {
                                Button("复制文件路径") { copyGitText(file.path) }
                            }
                        }
                    }
                    .padding(5)
                }
                .frame(width: 171)
                Divider()
                diffPreview.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(height: 235)
            .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 6))
        }
    }

    private var diffPreview: some View {
        Group {
            if untracked, let selection {
                VStack(alignment: .leading, spacing: 8) {
                    Text(selection.path).font(.caption.monospaced()).textSelection(.enabled)
                    Text("这个文件还没有 Git 版本。").font(.caption).foregroundStyle(.secondary)
                    Button("复制文件路径") { copyGitText(selection.path) }
                }
                .padding(10)
            } else if let diff {
                if diff.lines.isEmpty {
                    Text("此文件没有可显示的差异。").foregroundStyle(.secondary)
                } else {
                    ScrollView([.horizontal, .vertical]) {
                        // Measure every line so the scroll view gets the full patch width.
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(diff.lines.indices, id: \.self) { index in
                                let line = diff.lines[index]
                                Text(line.isEmpty ? " " : line)
                                    .foregroundStyle(line.hasPrefix("+") ? Color.green : line.hasPrefix("-") ? .red :
                                                     line.hasPrefix("@@") ? .blue : .primary)
                                    .font(.caption.monospaced())
                                    .fixedSize(horizontal: true, vertical: false)
                            }
                            if diff.truncated {
                                Text("只显示前 1,500 行或 512 KiB").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .fixedSize(horizontal: true, vertical: false)
                        .textSelection(.enabled)
                        .padding(8)
                    }
                    .accessibilityIdentifier("git-file-diff")
                }
            } else if failed {
                Text("暂时无法读取此文件的差异。").foregroundStyle(.secondary)
            } else {
                ProgressView().controlSize(.small)
            }
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "A": .green
        case "D": .red
        case "R": .purple
        default: .blue
        }
    }
}
