import SwiftUI

final class AvatarLoader {
    static let shared = AvatarLoader()

    private let images = NSCache<NSURL, NSImage>()
    private let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 12
        configuration.timeoutIntervalForResource = 20
        configuration.httpShouldSetCookies = false
        return URLSession(configuration: configuration)
    }()

    func image(at url: URL) async -> NSImage? {
        let key = url as NSURL
        if let cached = images.object(forKey: key) { return cached }
        guard let (data, response) = try? await session.data(from: url),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let image = NSImage(data: data) else { return nil }
        images.setObject(image, forKey: key)
        return image
    }
}

@MainActor
private final class AvatarModel: ObservableObject {
    @Published private(set) var image: NSImage?
    @Published var showPreview = false
    @Published private(set) var finished = false

    func load(_ url: URL) async {
        let loaded = await AvatarLoader.shared.image(at: url)
        guard !Task.isCancelled else { return }
        image = loaded
        finished = true
    }
}

struct AvatarView: View {
    let star: Star
    @StateObject private var model = AvatarModel()

    var body: some View {
        Button {
            model.showPreview = true
        } label: {
            thumbnail
        }
        .buttonStyle(.plain)
        .handCursor()
        .help("查看 \(star.login) 的头像大图")
        .accessibilityLabel("查看 \(star.login) 的头像大图")
        .task(id: star.avatarURL) { await model.load(star.avatarURL) }
        .sheet(isPresented: $model.showPreview) {
            AvatarPreview(star: star, thumbnail: model.image)
        }
    }

    private var thumbnail: some View {
        Group {
            if let image = model.image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
                    .accessibilityLabel("GitHub 头像")
            } else {
                Circle()
                    .fill(Color.accentColor.opacity(0.12))
                    .overlay {
                        Text(String(star.login.prefix(1)).uppercased())
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Color.accentColor)
                    }
                    .accessibilityHidden(true)
            }
        }
        .frame(width: 32, height: 32)
        .clipShape(Circle())
        .contentShape(Circle())
    }
}


private struct AvatarPreview: View {
    let star: Star
    let thumbnail: NSImage?
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = AvatarModel()

    var body: some View {
        VStack(spacing: 16) {
            HStack {
                Text(star.login).font(.headline).lineLimit(1)
                Spacer()
                Button("关闭") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
            ZStack(alignment: .bottom) {
                if let image = model.image ?? thumbnail {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 300, height: 300)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                        .accessibilityLabel("GitHub 头像大图")
                } else if model.finished {
                    ContentUnavailableView("头像加载失败", systemImage: "person.crop.circle")
                        .frame(width: 300, height: 300)
                } else {
                    ProgressView().frame(width: 300, height: 300)
                }

                if model.image == nil && thumbnail != nil {
                    Text(model.finished ? "大图暂时无法加载" : "正在加载大图…")
                        .font(.caption)
                        .padding(8)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6))
                        .padding(8)
                }
            }
        }
        .padding(20)
        .frame(width: 340)
        .task { await model.load(star.avatarURL(size: 640)) }
    }
}

extension View {
    @ViewBuilder
    func handCursor() -> some View {
        if #available(macOS 15.0, *) {
            pointerStyle(.link)
        } else {
            onHover { hovering in
                (hovering ? NSCursor.pointingHand : NSCursor.arrow).set()
            }
        }
    }
}
