# Star 记录（macOS）

用于查看 anki-pipeline 的项目数据、Star 增减与名单、Fork 记录，以及本地提交图和文件差异。公开统计来自 [GitHub Pages](https://chnragdoll.github.io/anki-pipeline/)，Git 记录读取本地检出。

## 构建和打开

App 最低支持 macOS 14。构建需要 macOS 15 SDK 或更新版本（Xcode 16 或对应版本的 Xcode Command Line Tools）。从 anki-pipeline 仓库根目录运行：

```sh
bash apps/star-roster/build.sh
open 'apps/star-roster/Star 记录.app'
```

脚本以当前 Mac 的架构构建并使用临时签名，默认输出到源码目录。也可将自定义 `.app` 路径作为第一个参数。

若需随 App 提供离线下载栏目，可用 `STAR_METRICS_PREVIEW_HTML` 指向通过 `scripts/project_metrics.py --snapshot …` 生成的 `index.html` 后构建。App 优先使用公开站，在线栏目不可用时显示带采集时间的内置快照。

## 配置 Git 记录

从默认构建位置打开时，App 自动使用该 checkout。若移动了 `.app` 或使用了自定义构建路径，在本地 anki-pipeline 仓库根目录运行以下命令，再重启 App：

```sh
defaults write local.anki-pipeline.star-roster repositoryPath -string "$(pwd -P)"
```

Git 记录的「刷新」从检出的 `origin` 更新远端跟踪分支，然后重读历史。可以查看提交和工作区文件差异。

## 项目数据与加密归档

项目数据中的公开统计和当前 Fork 列表可直接查看。「下载栏目」查看各科目、资料类型或做题本版式的跨版本累计和每日变化。窗口页首的时区入口作用于增减记录、当前名单和项目数据中可以换日界的图表。GitHub API 达到匿名速率限制时，部分查询可使用已登录的 GitHub CLI（`gh`）。

Star 名单及加密的 Fork 快照需要 GPG 和维护者已有的解密文件 `~/.local/share/anki-pipeline/star-roster/passphrase`。解密在本机完成，文件应保留在仓库外。具备访问权限时，可用以下命令检查 Star 归档读取：

```sh
'apps/star-roster/Star 记录.app/Contents/MacOS/StarRoster' --verify
```

## 搜索与下载

「项目数据 → 搜索与下载」可以按日期、Pages 落地页和下载栏目查看 GitHub 流量、Search Console、GA4 按钮点击及 Release 附件下载。下载栏目的增量沿用已有版本归档。各数据源沿用自己的报告日界，按钮点击和 Release 下载分别展示。

1. 在 Google Cloud 项目中启用 Google Search Console API 和 Google Analytics Data API，创建桌面应用 OAuth 客户端。首次配置时为 OAuth 应用设置受众。若使用测试模式，把有 Search Console 和 GA4 读取权限的 Google 账号加到测试用户中。
2. 在 App 点击「连接 Google」，选择桌面客户端 JSON，并在系统浏览器中授予只读权限。本机凭据保存在当前用户的 Application Support 目录，文件权限为 `0600`。在 Google 账号的第三方连接页面可撤销授权。
3. 在 GA4 为 Pages 创建 Web 数据流。把数据流的 Measurement ID 配为仓库 Actions 变量 `GA4_MEASUREMENT_ID`，将数字 Property ID 填入 App。
4. 在 GA4 创建事件范围的自定义维度，事件参数填写 `download_slot`。Pages 部署时识别 README 中的固定下载栏目，访客开启页面底部的点击统计后，在相关链接点击时发送 `release_download_click`。缺少 Measurement ID 或访客未开启统计时，页面不会加载 Google Analytics 标签。
5. 部署后使用 GA4 DebugView 核对点击事件，待 GA4 报表处理完成再在 App 中读取。Search Console 可读取已有搜索历史，GA4 点击从标签启用后开始积累。

Google 报表和 OAuth 授权信息仅由本地 App 使用。公开 Pages 包含启用点击采集所需的公开 Measurement ID。
