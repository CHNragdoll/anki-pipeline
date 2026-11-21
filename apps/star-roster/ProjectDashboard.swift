import SwiftUI
import WebKit

private enum MetricsModule: String, CaseIterable, Identifiable {
    case summary = "总览"
    case traffic = "流量"
    case acquisition = "搜索与下载"
    case downloads = "下载"
    case downloadSlots = "下载栏目"
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
        case .acquisition: "magnifyingglass.chart"
        case .downloads: "arrow.down.to.line"
        case .downloadSlots: "tablecells"
        case .calendar: "calendar"
        case .stars: "star"
        case .models: "chart.xyaxis.line"
        case .reconciliation: "checkmark.circle"
        case .forks: "arrow.triangle.branch"
        case .git: "point.topleft.down.to.point.bottomright.curvepath"
        }
    }

    var isWeb: Bool { self != .reconciliation && self != .forks && self != .git && self != .acquisition }

    var sections: [String] {
        switch self {
        case .summary: ["#project-summary", "#overview", "#activity"]
        case .traffic: ["#traffic", "#popular-traffic"]
        case .downloads: ["#download-history", "#download-comparison", "#download-files"]
        case .downloadSlots: ["#download-slots"]
        case .calendar: ["#maintenance"]
        case .stars: ["#stars", "#star-roster"]
        case .models: ["#star-impact", "#trend-models"]
        case .reconciliation, .forks, .git, .acquisition: []
        }
    }
}

@MainActor
private final class DashboardModel: ObservableObject {
    @Published var module = MetricsModule.summary
}

struct ProjectDashboard: View {
    let roster: Roster?
    let gitHistory: GitHistoryModel
    let refreshID: Int
    let timeZone: MetricsTimeZone
    @StateObject private var dashboard = DashboardModel()

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider()
            ZStack {
                MetricsPage(module: dashboard.module, refreshID: refreshID, timeZone: timeZone)
                    .opacity(dashboard.module.isWeb ? 1 : 0)
                    .allowsHitTesting(dashboard.module.isWeb)
                    .accessibilityHidden(!dashboard.module.isWeb)
                if dashboard.module == .acquisition {
                    AcquisitionView(refreshID: refreshID, timeZone: timeZone)
                } else if dashboard.module == .reconciliation {
                    ReconciliationView(roster: roster, refreshID: refreshID)
                } else if dashboard.module == .forks {
                    ForksView(refreshID: refreshID)
                } else if dashboard.module == .git {
                    GitHistoryView(refreshID: refreshID, model: gitHistory)
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
    let timeZone: MetricsTimeZone

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
        let timeZoneChanged = coordinator.timeZone != timeZone
        if module.isWeb { coordinator.module = module }
        coordinator.timeZone = timeZone
        if coordinator.refreshID != refreshID {
            coordinator.refreshID = refreshID
            coordinator.load(view)
        } else if moduleChanged {
            coordinator.changeModule(in: view)
        } else if timeZoneChanged {
            coordinator.applyTimeZone(in: view)
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        private enum PageSource { case hosted, preview, status }

        var module = MetricsModule.summary
        var refreshID: Int?
        var timeZone = MetricsTimeZone.beijing
        private var source = PageSource.hosted
        private var pendingNavigation: WKNavigation?
        private var pageRevision = 0

        func load(_ view: WKWebView) {
            source = .hosted
            view.alphaValue = 0
            pageRevision += 1
            pendingNavigation = view.load(URLRequest(url: ProjectMetrics.pageURL,
                                                     cachePolicy: .reloadIgnoringLocalCacheData,
                                                     timeoutInterval: 25))
        }

        func changeModule(in view: WKWebView) {
            if source == .status {
                load(view)
            } else if pendingNavigation == nil {
                showModule(in: view)
            }
        }

        func applyTimeZone(in view: WKWebView) {
            guard pendingNavigation == nil, source != .status else { return }
            view.callAsyncJavaScript("""
                const active = window.setMetricsTimeZone?.(zone);
                const sampleTime = document.getElementById('star-app-preview-time');
                if (sampleTime) sampleTime.textContent = document.getElementById('updated')?.textContent || '';
                return active;
                """,
                                     arguments: ["zone": timeZone.rawValue], in: nil, in: .page,
                                     completionHandler: nil)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard pendingNavigation == nil || pendingNavigation === navigation else { return }
            pendingNavigation = nil
            if source == .status {
                webView.alphaValue = 1
            } else {
                showModule(in: webView)
            }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: any Error) {
            finishFailedNavigation(in: webView, navigation: navigation, error: error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) {
            finishFailedNavigation(in: webView, navigation: navigation, error: error)
        }

        private func finishFailedNavigation(in view: WKWebView, navigation: WKNavigation?, error: any Error) {
            guard pendingNavigation == nil || pendingNavigation === navigation else { return }
            pendingNavigation = nil
            guard (error as NSError).code != NSURLErrorCancelled, source != .status else { return }
            showPreview(in: view)
        }

        private func showPreview(in view: WKWebView) {
            if source == .hosted,
               let url = Bundle.main.url(forResource: "ProjectMetricsPreview", withExtension: "html"),
               let html = try? String(contentsOf: url, encoding: .utf8) {
                source = .preview
                pageRevision += 1
                pendingNavigation = view.loadHTMLString(html, baseURL: ProjectMetrics.pageURL)
            } else {
                showStatus(in: view, title: "项目数据暂时无法加载",
                           detail: "检查网络后，点击窗口右上角的「刷新」。")
            }
        }

        private func showStatus(in view: WKWebView, title: String, detail: String) {
            source = .status
            pageRevision += 1
            pendingNavigation = view.loadHTMLString("""
            <meta charset="utf-8"><style>body{font:15px -apple-system;padding:24px;color:CanvasText;background:Canvas;color-scheme:light dark}</style>
            <h2>\(title)</h2><p>\(detail)</p>
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

        private func showModule(in view: WKWebView) {
            guard source != .status else { return }
            let sections = module.sections
            let isModel = module == .models
            let isPreview = source == .preview
            let selected = module
            let revision = pageRevision
            view.callAsyncJavaScript("""
                const main = document.querySelector('main');
                const chosen = sections.map(s => main?.querySelector(s)).filter(Boolean);
                if (!main || chosen.length !== sections.length || typeof window.setMetricsTimeZone !== 'function') {
                    if (main) main.hidden = true;
                    return false;
                }
                main.hidden = false;

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
                      main > header, .summary-links, #metrics-timezone-control { display: none !important; }
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
                window.setMetricsTimeZone(zone);
                if (isPreview) {
                    let note = document.getElementById('star-app-preview-note');
                    if (!note) {
                        note = document.createElement('p');
                        note.id = 'star-app-preview-note';
                        note.className = 'hint';
                        const sampleTime = document.createElement('span');
                        sampleTime.id = 'star-app-preview-time';
                        note.append('App 内置快照 · ', sampleTime, '。点击窗口右上角的「刷新」可重试在线数据。');
                    }
                    note.querySelector('#star-app-preview-time').textContent = document.getElementById('updated')?.textContent || '';
                    if (note.parentElement !== chosen[0]) chosen[0].prepend(note);
                }
                spaceMonthLabels();
                document.querySelector('#tooltip')?.setAttribute('hidden', '');
                // Draw after exposing the chosen sections so SVGs use their real width on the first frame.
                for (const draw of [
                    window.drawTraffic, window.drawStars, window.drawDownloads, window.drawDownloadRelease,
                    window.drawDownloadSlotTrend, window.drawModels, window.drawProjectSummary
                ]) {
                    if (typeof draw === 'function') draw();
                }
                window.scrollTo(0, 0);
                return true;
                """, arguments: ["sections": sections, "isModel": isModel, "isPreview": isPreview,
                                  "zone": timeZone.rawValue],
                in: nil, in: .page) {
                [weak self, weak view] result in
                guard let self, let view, self.module == selected, self.pageRevision == revision else { return }
                if case .success(let shown) = result, shown as? Bool == true {
                    view.alphaValue = 1
                    return
                }
                self.showPreview(in: view)
            }
        }
    }
}
