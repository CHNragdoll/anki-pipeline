# 本地操作、验证与恢复

当前源码候选版为 **3.0.0-rc.3**。项目主页 [README.md](../README.md) 展示完整功能、截图、算法和图示；本文集中说明逐步执行命令与数据写入边界。rc.1 / rc.2 的发布决定与测试是历史记录，不能代替本轮验收。

## 1. 准备目录和输入

以下命令从仓库根目录执行。先修改 `config.toml`，确认源资料和新输出路径正确。相对路径按配置文件位置解析，不按终端当前目录解析；可写路径必须位于 `project.root` 内。省略 `project.root` 时，使用配置文件所在目录。

| 输入 | 用途与准备要求 |
| --- | --- |
| `paths.legacy_database`、`wordbook`、`legacy_audio` | 首次迁移的原 V2.0 资料；已有新版库时不用再次迁移 |
| `paths.database`、`audio` | 已迁移的新版 SQLite 与基础音频；Git 不包含这些文件 |
| `local_dictionary.root` | 已解包的牛津、韦氏数据库及资源；韦氏解析 helper 也须存在 |
| `ecdict.root` | 本地 ECDICT 输入；用于完整词性/释义回退、词形和考试标签 |
| `etymology.root` | 已解包词源资源及解析 helper；查看生成卡片不需要词源服务 |
| `exam_library.root` | 配套真题仓库，包含结构化题目、答案、译文和来源定位资源 |
| `exam_library.codex_index_root` | 内容一致的 Codex 逐句索引，不是仅有目录即可 |
| `exam_library.reading_completion_path` | 已审校阅读题干补全 JSON，路径相对配置文件；省略时 Codex 模式使用 `project.root/data/reading-completions-v1.json` |
| 同目录的补全/候选译文 review | `reading-completions-v1.review.json`、`reading-option-translations-v1.json`、`reading-option-translations-v1.review.json` 以及审校记录引用的作者/独立审校文件 |

批准侧车和审校文件必须与实际来源哈希一致；不能复制一份旧 review 去批准修改后的译文。原始数据库、词典媒体、完整真题、CSV、APKG 和私有审校输入不会随干净 Git checkout 自动出现。源码、CLI、测试安装成功，与本机完整学习输入准备好是不同检查。

## 2. 安装与只读检查

Python 元数据要求 `>=3.11`；JavaScript 行为测试使用项目 Node 依赖，Node 支持 `^20.19.0 || ^22.13.0 || >=24.0.0`，CI 使用 Node 24。

```sh
cd /你的路径/anki-pipeline
uv sync --frozen --extra dev --no-editable
uv run --no-editable anki-pipeline --version
uv run --no-editable anki-pipeline --help
uv run --no-editable anki-pipeline doctor
```

`doctor` 检查配置、依赖和输入路径存在性，不证明译文语义、原始资料完整性或 Anki 客户端兼容性。使用普通安装避免本机 editable `.pth` 曾出现的隐藏标记问题。

干净源码验证不需要学习资料：

```sh
uv run --no-editable python -m unittest discover -s tests -v
uv run --no-editable python scripts/verify_project.py
npm ci
npm run check
npm test
```

`npm run check` 检查模板脚本语法；`npm test` 执行卡片启动、chunk、倒计时、词典音频、网页目录、播放按钮样式和逐句朗读行为测试。模拟 DOM 测试不证明真机已播放出声音。

## 3. 首次迁移：只用于尚未准备新版库的环境

已有 `data/anki.sqlite3` 且来源已核对时跳过本节。停止对原 V2.0 SQLite 的并发写入，确认新旧路径不同，再执行：

```sh
uv run --no-editable anki-pipeline migrate
uv run --no-editable anki-pipeline check --report output/quality-check.json
```

`migrate` 读取旧资料，创建旧库快照，生成独立新版库，复制音频并登记源 SHA-256。它保存被隔离的句子，不修改原文、原译或原媒体。遇到不同来源的既有目标库会停止，不覆盖它。

数据库提升后才复制音频；若复制失败，新库和部分新版媒体可能已经存在。保留现场，修复缺失或不安全的原音频路径后重跑迁移，它只补缺失新版音频。不要删除 V2.0 原资料作为恢复手段。

`check` 的一般警告不一定使退出码非零。需要所有已接受句子都有译文时，使用：

```sh
uv run --no-editable anki-pipeline check --report output/quality-strict.json --strict-translations
```

基础数据错误或严格模式下仍有待补译文时退出码为 2。当前真题快照的统计与旧库质量报告分开核对，不将旧库句子量当作最终题库例句量。

## 4. 人工译文、词表与 PDF 输入

导出翻译 CSV：

```sh
uv run --no-editable anki-pipeline export-translations --file output/pending-translations.csv
```

每句一行，只编辑 `translation` 列；保留 `sentence_id`、`word`、`text`、`source`、`content_hash` 和 `translation_revision`。空译文不抹去已有译文，乱序通过 ID 对齐。保留填写完成的工作表，再导入：

```sh
uv run --no-editable anki-pipeline import-translations --file output/completed-translations.csv
uv run --no-editable anki-pipeline check --report output/quality-after-translations.json --strict-translations
```

程序先核验整个文件，再事务写入。重复 ID、改动原文、过期哈希或旧译文版本会阻止导入，不先写半份文件。CSV 含学习文本，保留在 Git 外。

新增词表或 PDF 只写新版数据库：

```sh
uv run --no-editable anki-pipeline import-wordbook --file /你的路径/词表.xlsx
uv run --no-editable anki-pipeline extract --pdf /你的路径/真题.pdf
```

`extract` 必须指定 `--pdf` 或配置 `paths.pdf`。新 PDF 例句没有经过自动翻译，空译文进入人工核验；词表空字段不覆盖已有补全内容。两种写入后重新 `check`。

修改词形规则或明确词形后，重新分类旧例句：

```sh
uv run --no-editable anki-pipeline reclassify
uv run --no-editable anki-pipeline check --report output/after-reclassify.json
```

重新分类在改变接受判定前备份，保留原文和译文。新接受的句子仍可能需要翻译。

## 5. 生成 APKG、全卡组网页与离线包

已准备完整输入后：

```sh
uv run --no-editable anki-pipeline check --report output/quality-before-build.json
uv run --no-editable anki-pipeline build --file output/anki-rebuilt-3.0.0rc3.apkg
uv run --no-editable anki-pipeline web-preview
```

`build` 写 APKG、单卡 `preview.html`、质量与构建报告。`web-preview` 只生成全部卡组的网页入口和共享资产，不重打 APKG，也不覆盖现有构建报告。两者从源库和配套索引只读取数，在内存中补题干/选项/词典内容，不把展示补全写回源数据库或原卷。

双词典整套本地产物：

```sh
uv run --no-editable anki-pipeline offline-bundle --file output/offline-review-3.0.0rc3.apkg
```

它要求 `local_dictionary.root`，输出指定 APKG、`preview-library.html`、`Anki-完整网页预览.zip` 和交付报告。生成文件先检查再提升；网页资源按内容摘要保留旧版本。若构建中源 SQLite 摘要变化，生成器拒绝发布新结果。

命名的已交付卡包位于：

```text
output/27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版.apkg
```

上述命令故意使用另一个核对包文件名，不覆盖该交付文件。改名后的当前包沿用其已检查的身份；全新重建涉及牌组命名等输入时，必须重新核对 deck / model / GUID / card 身份，不能仅凭同版本号推断兼容。

## 6. 实际预览与真题联动

在另一个终端启动卡片静态服务：

```sh
uv run --no-editable python -m http.server 8771 --bind 127.0.0.1 --directory output
```

打开 <http://localhost:8771/preview-library.html>。该网页不需要运行 `8770` 词典 API，录音与词源资源已打包。

按配套 [exam-library](https://github.com/CHNragdoll/exam-library) 的启动说明运行真题服务，使配置中的 `http://localhost:8765` 可访问。点击例句来源前，先选择 LaTeX 或整卷练习；卡片传递原句 ID、来源哈希和必要的双向上下文，真题端核验后框出对应内容。普通整卷练习仍保留原空格，不因为卡片生成而写入回填答案。

在实际页面检查：

1. 正面与背面词头样式一致、发音选择器在左上；切来源后实际播放录音。
2. 释义、词形、派生词、词源、词频和全部例句完整，窄屏没有横向溢出。
3. 英文和中文分别悬停/点击可激活现成 chunk 对应，取消后恢复。
4. 从至少几个不同来源实际点击，记录点击前及落地后的定位外框。
5. 双向合并例句在原题同时框题干与对应正确项，其他例句按其原定位逻辑处理。
6. 完形四项一行、短 Part B 选项库两列、排序五个字母一行；实际选择与查看答案。
7. 重绘图首次打开即按规定尺寸显示，切原图/重绘图后无尺寸突变。
8. 倒计时位于例句内容末尾右侧，在内容上方阅读时不盖住正文。

这些页面能力需要配套仓库的对应接收端实现。当前本机联动截图不能自动证明远程旧提交已包含全部能力。网页工具没有 Anki 排程和评分，也不替代真实设备导入。

离线网页 ZIP 必须整个解压：

```sh
python3 serve_preview.py
```

在解压后的目录执行；macOS 也可双击 `启动网页预览.command`。它只使用 Python 标准库，在随机本机端口服务包内文件，关闭终端或 `Ctrl+C` 停止。词卡浏览和录音离线可用；打开原卷仍需要对应真题服务。另一设备的 `localhost` 指该设备自身。

## 7. 显式联网补全与逐句朗读

仅在确实需要补充词典字段时执行：

```sh
uv run --no-editable anki-pipeline enrich --provider oxford --limit 10
uv run --no-editable anki-pipeline enrich --provider youdao --limit 10
```

`--limit` 必须为 1–100；命令按词逐个报告结果，已有人工修正受保护。它会发送查询词，牛津可能下载 MP3，不自动定时运行。页面变化或请求失败会报告，不把失败当作成功补全。

卡片逐句扬声器是另一条显式点击路径：发送该句英文到有道 HTTPS，不发送中文或整个词库；失败或加载/停顿超时后尝试系统语音。再次点击、切换句子或翻面会停止先前播放。打开卡片不会自动发送句子请求。单词录音播放使用卡包本地媒体。

## 8. 备份、恢复与对账

```sh
uv run --no-editable anki-pipeline backup
uv run --no-editable anki-pipeline restore --file backups/NAME.sqlite3 --to data/restored-for-review.sqlite3
```

`backup` 使用 SQLite 在线备份 API 并检查完整性。`restore` 只写尚不存在的新路径，不覆盖当前库。

下一步复制配置到项目内的私人临时文件，将其 `paths.database` 改为恢复路径。然后核对：

```sh
uv run --no-editable anki-pipeline --config config.restore.toml doctor
uv run --no-editable anki-pipeline --config config.restore.toml check --report output/restored-quality.json
```

普通 `check` 仍读取当前配置的活动库，不自动读取刚恢复的新文件。比较恢复前后逻辑摘要、表行数、样本 ID、译文版本和媒体后，再人工调整活动配置。保留分离存储的备份及保留时间；APKG 不是 SQLite 和人工译文工作表的备份替代品。

流水线回滚可继续使用保留的旧包和旧网页版本。用户真实 Anki 集合的笔记/进度恢复应使用导入前的 Anki 备份，直接导入旧包不保证模板和字段回退。此运行手册不自动操作用户档案或同步。

## 9. 版本、Release 与许可

`pyproject.toml`、`anki_pipeline.__version__` 和 `uv.lock` 使用 `3.0.0rc3`；项目档案使用 `3.0.0-rc.3`。本轮版本与 PR 的范围见 [RELEASE_RC3.md](RELEASE_RC3.md)，真实提交、CI、审查与发布状态由最终执行记录确认。

用户要求本轮 GitHub Release **手工上传资产仅一个 APKG**。Markdown、截图和各项说明保留在仓库；不额外上传 PDF、ZIP 或报告。GitHub 自动提供的源码归档不是手工附加资产。历史版本的等效控制批准不自动延续到新版本。

本仓库原创代码使用 [MIT License](../LICENSE)，第三方词典、词表、真题、音频及依赖各自许可不变。wheel 元数据应包含 `License-Expression: MIT` 和打包的 `LICENSE`；检查安装包元数据不能替代第三方素材许可核查。
