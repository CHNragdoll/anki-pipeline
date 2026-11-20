import SwiftUI
import WebKit

private enum MetricsModule: String, CaseIterable, Identifiable {
    case summary = "总览"
    case traffic = "流量"
    case downloads = "下载"
    case calendar = "日历图"
    case stars = "Star 趋势"
    case models = "模型"
    case reconciliation = "净增核对"
    case forks = "Fork"
    case git = "Git 记录"

    var id: Self { self }

    var symbol: String {
        switch self {
        case .summary: "rectangle.grid.2x2"
        case .traffic: "person.2"
        case .downloads: "arrow.down.to.line"
        case .calendar: "calendar"
        case .stars: "star"
        case .models: "chart.xyaxis.line"
        case .reconciliation: "checkmark.circle"
        case .forks: "arrow.triangle.branch"
        case .git: "point.topleft.down.to.point.bottomright.curvepath"
        }
    }

    var isWeb: Bool { self != .reconciliation && self != .forks && self != .git }

    var sections: [String] {
        switch self {
        case .summary: ["#project-summary", "#overview", "#activity"]
        case .traffic: ["#traffic", "#popular-traffic"]
        case .downloads: ["#download-history", "#download-comparison", "#download-files"]
        case .calendar: ["#maintenance"]
        case .stars: ["#stars", "#star-roster"]
        case .models: ["#star-impact", "#trend-models"]
        case .reconciliation, .forks, .git: []
        }
    }
}

@MainActor
private final class DashboardModel: ObservableObject {
    @Published var module = MetricsModule.summary
}

struct ProjectDashboard: View {
    let roster: Roster?
    let refreshID: Int
    @StateObject private var dashboard = DashboardModel()

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider()
            ZStack {
                MetricsPage(module: dashboard.module, refreshID: refreshID)
                    .opacity(dashboard.module.isWeb ? 1 : 0)
                    .allowsHitTesting(dashboard.module.isWeb)
                    .accessibilityHidden(!dashboard.module.isWeb)
                if dashboard.module == .reconciliation {
                    ReconciliationView(roster: roster, refreshID: refreshID)
                } else if dashboard.module == .forks {
                    ForksView(refreshID: refreshID)
                } else if dashboard.module == .git {
                    GitHistoryView(refreshID: refreshID)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var sidebar: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(MetricsModule.allCases) { module in
                    if module == .reconciliation {
                        Divider().padding(.horizontal, 6).padding(.vertical, 8)
                    }
                    moduleButton(module)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 14)
        }
        .frame(width: 145)
        .background(Color(nsColor: .controlBackgroundColor))
        .accessibilityIdentifier("metrics-modules")
    }

    private func moduleButton(_ module: MetricsModule) -> some View {
        let selected = dashboard.module == module
        return Button {
            dashboard.module = module
        } label: {
            HStack(spacing: 9) {
                Image(systemName: module.symbol)
                    .font(.system(size: 13, weight: selected ? .semibold : .medium))
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                    .frame(width: 18)
                    .accessibilityHidden(true)
                Text(module.rawValue).font(.system(size: 13, weight: selected ? .semibold : .regular))
                Spacer(minLength: 0)
            }
            .foregroundStyle(selected ? Color.accentColor : Color.primary)
            .padding(.horizontal, 9)
            .frame(height: 32)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color.accentColor.opacity(0.12))
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .handCursor()
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier("metrics-\(module)")
    }
}

private struct MetricsPage: NSViewRepresentable {
    let module: MetricsModule
    let refreshID: Int

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.allowsMagnification = true
        updateNSView(view, context: context)
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        let coordinator = context.coordinator
        let moduleChanged = coordinator.module != module && module.isWeb
        if module.isWeb { coordinator.module = module }
        if coordinator.refreshID != refreshID {
            coordinator.refreshID = refreshID
            coordinator.load(view)
        } else if moduleChanged {
            coordinator.showModule(in: view)
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        var module = MetricsModule.summary
        var refreshID: Int?

        func load(_ view: WKWebView) {
            view.load(URLRequest(url: ProjectMetrics.pageURL, cachePolicy: .reloadIgnoringLocalCacheData,
                                 timeoutInterval: 25))
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            showModule(in: webView)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: any Error) {
            guard (error as NSError).code != NSURLErrorCancelled else { return }
            webView.loadHTMLString("""
            <meta charset="utf-8"><style>body{font:15px -apple-system;padding:24px;color:CanvasText;background:Canvas;color-scheme:light dark}</style>
            <h2>项目数据暂时无法加载</h2><p>检查网络后，点击窗口右上角的「刷新」。</p>
            """, baseURL: nil)
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if url.scheme == "about" || ProjectMetrics.isPage(url) {
                decisionHandler(.allow)
            } else {
                if navigationAction.navigationType == .linkActivated, url.scheme == "https" {
                    NSWorkspace.shared.open(url)
                }
                decisionHandler(.cancel)
            }
        }

        func showModule(in view: WKWebView) {
            let sections = module.sections
            let isModel = module == .models
            view.callAsyncJavaScript("""
                const main = document.querySelector('main');
                const chosen = sections.map(s => main?.querySelector(s)).filter(Boolean);
                if (!main || !chosen.length) return false;

                const heatmap = main.querySelector('#heatmap');
                const spaceMonthLabels = () => {
                    if (!heatmap?.getClientRects().length) return;
                    const labels = [...heatmap.querySelectorAll('svg text')]
                        .filter(label => /^[0-9]{2}月$/.test(label.textContent.trim()));
                    let boundary = Infinity;
                    for (const label of labels.reverse()) {
                        const box = label.getBBox();
                        const visible = box.x + box.width + 5 <= boundary;
                        label.style.visibility = visible ? '' : 'hidden';
                        if (visible) boundary = box.x;
                    }
                };
                if (!document.getElementById('star-app-style')) {
                    const style = document.createElement('style');
                    style.id = 'star-app-style';
                    style.textContent = `
                      [data-star-app-hide] { display: none !important }
                      main { padding: 0 20px 26px; }
                      main section { padding: 17px; margin: 12px 0; }
                      main > header, .summary-links { display: none !important; }
                      #project-summary[data-star-app-model] { border: 0; background: transparent; padding: 0; }
                      #project-summary[data-star-app-model] > .controls > div { display: none; }
                      #project-summary[data-star-app-model] > .controls > label { margin-left: auto; }
                      main > .pair { grid-template-columns: minmax(0, 1fr); gap: 12px; }
                      main > footer { margin-top: 16px; }
                    `;
                    document.head.append(style);
                    if (heatmap) {
                        new MutationObserver(spaceMonthLabels).observe(heatmap, {childList: true, subtree: true});
                    }
                }

                const summary = main.querySelector('#project-summary');
                const summaryControls = summary?.querySelector(':scope > .controls');
                const impact = main.querySelector('#star-impact');
                const apply = (node, hide) => node?.toggleAttribute('data-star-app-hide', hide);
                for (const child of main.children) {
                    if (child.tagName === 'FOOTER') continue;
                    apply(child, !chosen.some(section => child.contains(section)));
                }
                if (summary) {
                    summary.toggleAttribute('data-star-app-model', isModel);
                    for (const child of summary.children) {
                        apply(child, isModel ? child !== impact && child !== summaryControls : child === impact);
                    }
                }
                spaceMonthLabels();
                document.querySelector('#tooltip')?.setAttribute('hidden', '');
                window.scrollTo(0, 0);
                return true;
                """, arguments: ["sections": sections, "isModel": isModel], in: nil, in: .defaultClient, completionHandler: nil)
        }
    }
}
