# 首页项目数据

`scripts/project_metrics.py` 从当前 README 下载表读取五本书的正式 APKG、卡数与有卡分组。新增书籍或更新下载表后，概览随下次采集更新，无需另写一份数量。

## 口径

- 标题的 APKG 下载：所有公开 Release 中 `.apkg` 附件的下载次数之和，包含历史版本；排除校验、JSON、补丁等附件。是下载次数，不是用户人数。
- 下载表中的单书下载：该固定发行页下所有 APKG 附件累计下载；概览同时列出“当前包下载”（表中链接的那一个 APKG）和“全部版本下载”（固定发行页所有 APKG）。两者明确区分。
- 16,807 张卡是五个完整包的卡数合计，包含说明／查阅卡；跨年份和跨书可能重复，不是去重知识点数。
- 1,631 道试题只统计政治和408，不把英语例句当独立试题相加。
- PV、每日 UV、Clone 和每日独立克隆者来自 GitHub Traffic，按 GitHub 的 UTC 日界展示；不能把每日 UV 相加作为区间独立访客。
- 接口返回日期覆盖旧记录，包括下修；未返回的日期不补零。当天数据可能未完整。图中单独标出数据截止日与采集时间，GitHub 有延迟时不伪造最近日期。
- 每日归档保存到 `project-metrics` 数据分支的 `history.json`，历史不依赖 Actions 临时 artifact。该分支只包含公开统计、SVG 和自包含交互页，不含凭据，不修改 main。
- Star 时间分布根据**当前仍保留 Star** 的 `starred_at` 重建，不含已取消的 Star，不冒充完整净增长历史。归档另保存实际每日 Star 总量，未来可用来做净增长分析。
- 活动面板按当前仓库显示 Star、Fork、开放 Issue＋PR、近30天提交与 GitHub 语言字节比例；语言比例不是卡包资料占比。这里用同一生成器实现 Metrics 类项目面板，避免再接入一套个人统计服务和额外令牌。

## 可交互统计与维护热力图

README 通过 `img/picture` 嵌入 SVG，不能运行脚本或保证图片内部的逐点悬停提示。因此静态图直接标注数据点数值；活动面板默认折叠。

同一快照还生成 `index.html` 自包含交互页，无第三方 CDN、无需令牌、可离线打开。访客、克隆、Star 和维护热力图支持悬停提示、点击固定、再次点击／Esc取消、键盘焦点及方向键查看，手机可点按；支持时间范围切换和逐日明细表。数据只在本地 DOM 解析，不发送到其他服务。

维护热力图来自 GitHub 默认分支近366天的提交，按提交者日期（UTC）归档，不是所有仓库贡献，也不是推送次数。包含合并提交，尚未合并的本地维护分支不计入。未获本次采集数据的旧快照不应显示一整年零活动。

本地交互入口：`http://127.0.0.1:8771/readme-project-metrics/assets/project-metrics/index.html`；局域网入口将主机替换为电脑 IP。GitHub 内直接打开 HTML 文件只会查看源码；要供公众交互使用，发布时需将数据分支的 `index.html` 部署为静态网站（如 GitHub Pages），并在验证实际地址后更新 README 链接。不能声称 README 图片本身可运行脚本。

## 更新与权限

工作流 `.github/workflows/project-metrics.yml` 每小时第23分钟（GitHub 调度可能延迟）、修改相关 main 文件后、或手动触发时运行。先取数据分支的归档，再采集并只向该数据分支提交。常规 `GITHUB_TOKEN` 负责写该分支，main 仍遵守 PR 和逐次合并确认。

当前本地 README 使用仓库内真实快照的相对路径，编辑器和离线预览都可直接显示，不提前引用尚不存在的远端图片。获准发布后，先初始化并验证数据分支，再执行 `python3 scripts/project_metrics.py --activate-remote-links`，将 README 切换至该分支的实时 SVG。该命令会匿名验证全部图片和快照，任何一个失败都不修改 README；随后按正常 PR 流程发布这次链接切换。切换前只能称快照预览，不能称每日自动展示已启用。

GitHub Traffic 接口需要额外的仓库 Administration 读取权限，普通 Actions `GITHUB_TOKEN` 通常不足。配置仓库 Secret **`PROJECT_METRICS_TOKEN`**：使用仅选择本仓库的细粒度令牌，权限 **Administration: read、Contents: read**（Metadata: read 自动附带）。不要把个人 `gh auth token` 的宽权限令牌复制到这里。该令牌只读；数据分支写入继续使用短期 `GITHUB_TOKEN`。

缺少专用 Secret 时，公开数据仍更新，Traffic 保留最近一次真实数据并标注本次不可读取，Actions 发出警告，不将失败值写成零。令牌撤销或过期时同样处理。GitHub 仅提供滚动14天 Traffic，漏采超过窗口的历史无法回补。

本地首轮使用电脑已有的 gh 授权读取官方数据，不创建或导出新凭据。**本次交付是本地预览；工作流合并到 main 且配置专用 Secret 后，远端每小时采集才会生效。**

## 本地复现

```sh
python3 scripts/project_metrics.py
python3 scripts/project_metrics.py --snapshot assets/project-metrics/snapshot.json --output output/metrics-offline
python3 -m unittest tests.test_project_metrics -v
# 可选浏览器回归（本地安装 puppeteer-core 后）
PUPPETEER_CORE_PATH=/path/to/node_modules/puppeteer-core node scripts/verify_project_metrics_browser.cjs
```

`assets/project-metrics/` 是随代码保留的真实首轮快照和离线预览兜底。自动更新以数据分支为准。脚本只使用 Python 标准库与 GitHub CLI；不读学习记录、PostgreSQL 或个人集合，也不修改卡包。

## 回退

禁用 Project metrics 工作流即可停止自动采集；将 README 图片链接改回 `assets/project-metrics/*.svg` 可使用随代码保存的快照。归档和源码均保留；不要为一次采集失败删除数据分支。

概览使用“考研408历年真题”和“考研政治历年真题”完整名称。交互页的每个卡包名称链接到其固定 Release 页；README 图片下另有对应文本链接，避免依赖图片内部链接。当前访客与克隆逐日存档覆盖 2026-10-18—2026-10-31；持续自动采集需先发布并启用工作流，未采集的早期日期不能补回。

交互页“刷新数据”通过 no-store 请求读取最新 snapshot；有新快照时重新载入页面，无新数据时明确显示原采集时间。按钮不携带令牌、不伪装为实时 GitHub 采集；需要立刻重新采集时，使用旁边的 GitHub Actions 入口手动触发工作流。README 概览使用原生表格，卡包名称及下载徽章均链接对应固定 Release，仓库活动默认折叠。
