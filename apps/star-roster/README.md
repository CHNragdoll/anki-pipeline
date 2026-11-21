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
