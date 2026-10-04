# v3.0.1 移动端复习、滚动和词源发布记录

日期：2026-10-04（Asia/Shanghai）。维护者明确要求把本次修复发布到 GitHub。源码与唯一 APKG 附件的正式发布流程如下；记录本身不表示 PR 已获准合并或 Release 已上线。

## 修复范围

旧倒计时脚本设置固定视口高度、flex 零基准尺寸和隐藏溢出内容，接管了 Anki 客户端的文档布局。AnkiDroid 复习使用 `body > #content > #qa`，与单卡预览结构不同；在真实浏览器复现中，嵌套卡片高度被压到 0，解释了预览正常而复习正面空白、背面闪现后消失的现象。

新版在普通文档流中排列卡片，不再修改 `html` / `body` / 原生复习宿主的高度、布局类或滚动方式。倒计时仍在卡片内容末尾，背面位于最后一条例句翻译之后，不占用固定底部横栏。换卡、翻面、计时器清理、旧版挂载状态升级回收继续生效。

变更包括：

- `anki_pipeline/templates/countdown.js`：宿主支持 `#qa`、旧版 `#content` 和普通网页；不接管客户端外壳。
- `anki_pipeline/templates/style.css`：内容高度自动增长、溢出可见。
- `tests/test_countdown.cjs`：增加嵌套及旧版 AnkiDroid 宿主、翻面/换卡、客户端 class 保留、旧脚本热升级回归。
- 当前 APKG 的正面、背面模板及全部 1,960 张笔记 Meta 中的旧脚本同时替换。只改外部模板不足以更新这些保留字段。
- `pyproject.toml`、`__version__`、`uv.lock`、项目档案统一为 `3.0.1`；首页保留全部功能、命令、算法、交互、Mermaid 和旧截图，并加入本次真机证据。

词源仍为已打包的离线内容。此修复使其所在长背面恢复可见和可滚动；本次没有新增词根资料，也没有声称 AnkiWeb 的共享页字段表会执行卡片脚本。

## 唯一 Release 附件

| 项目 | 已核对内容 |
|---|---|
| 下载文件名 | `Anki-2027-LiuXiaoyan-Ebbinghaus-v3.0.1.apkg` |
| 卡组显示名 | `27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版` |
| 字节数 | `85835717`（约 85.84 MB） |
| SHA-256 | `731614b6121a86593b37feb8ad8c31df9e7446521fb6942585130ad7dabad565` |
| 笔记 / 卡片 | 1,960 / 1,960 |
| 课程分组 | 41 |
| 录音 | 6,530 个 MP3 |
| 展示例句合计 | 20,178 |
| 包格式 | 真实数据为 `collection.anki21`；附兼容提示用的 `collection.anki2`，不能把提示数据库误当成学习数据库 |

发布附件是已经在华为导入验证的修复包的逐字节副本，修改文件名不重新生成媒体或学习资料。ZIP CRC 和真实 SQLite `integrity_check` 通过。相对本次手机来源包，卡片 ID、笔记 GUID、原调度和所有非真实数据库的 ZIP 资源逐字节不变，笔记字段只更新 Meta 辅助脚本；原始来源包保留。

旧 v3.0.0 附件 239,063,203 bytes 没有覆盖。旧包 ZIP 条目未压缩，本次真实集合使用 DEFLATE 压缩，体积减少主要来自压缩方式，不能据此推断删掉了词源或录音。与旧正式版的来源、卡组和字段差异见 [包核对记录](release-v3.0.1-verification.json)。GUID、模型 ID 与卡片 ID 保留；仍须由 Anki 客户端执行更新导入及集合备份，不能把卡包当成个人学习进度备份。

### 与旧正式版的逐项对账

- 1,960 张卡的笔记 GUID、note/card ID、模型数字 ID 和命名 Lesson 一致；6,530 个录音逐文件 SHA-256 一致，Examples 字段及 20,178 条展示例句一致。
- 1,951 条词源记录保留；Definition 差异仅为客户端导出的换行和 NFC Unicode 归一化，归一化后内容一致。
- 两包都没有 revlog / graves 行，Note 私人笔记字段为空，全部卡都是未复习新卡。没有把维护者的个人复习历史带入公开附件。
- 相对旧 Release，deck ID 被导出重编，但全部卡仍属于同名课程；同步标记及空 JSON 元数据也变化。不能宣称数据库全行逐字节相同。实际调度列不变。
- 旧包为 legacy `collection.anki2`，本次为 `collection.anki21` 加兼容提示库和 meta，需要目标客户端支持 Anki 2.1 时代的 APKG 格式。华为 2.20.1 已实际导入；未验证的旧客户端不作兼容承诺。

## 直接观察的设备证据

2026-10-04，华为 OCE-AN10，Android API 31，AnkiDroid 2.20.1。通过 Android Studio 镜像操作实际 USB 手机，没有用模拟器或静态网页代替真机。

1. 导入修复包，导入结果显示新增 1,960 条笔记。
2. 实际进入 Lesson 01 / 02 / 03 复习，分别检查 ambition、embarrass、fare 的正面与显示答案后的持续背面。
3. ambition 背面词源树和词根词缀可见；继续向下滑动到第 23 条例句、中文翻译和内容末尾倒计时。
4. 未点击评分按钮，未将个人集合或设备备份上传到仓库或 Release。

截图目录统一为 [`assets/screenshots/v3.0.1/`](../assets/screenshots/v3.0.1/)，捕获方式、具体适用范围和 SHA-256 见 [capture-manifest.json](../assets/screenshots/v3.0.1/capture-manifest.json)。正反面并列图表示两种实际状态，不表示连续视频；embarrass 正面在背面之后重新捕获。

| 范围 | 状态和边界 |
|---|---|
| 华为实际复习正反面 | **PASS**：三个 Lesson 的三个词；不外推为全部设备、全部交互测试。 |
| 华为词源 / 长卡滚动 | **PASS**：ambition 词源可见且可到最后例句。 |
| iPhone / AnkiMobile | **维护者反馈已恢复滚动和词根显示**；本轮没有新增 iPhone 真机测试，不能标成代理直接验收 PASS。 |
| ZIP / 数据库 / 媒体 | **PASS**：CRC、真实数据库完整性、数据与媒体比对。 |
| Node 回归 | **PASS**：68 / 68；含客户端嵌套宿主和布局生命周期。 |
| Python 回归 | **PASS**：431 / 431；无新增依赖版本。 |
| 项目档案 / 版本 / 语法 | **PASS**：92 条映射、版本一致性、模板脚本分离。 |
| 当前 PR 的 CI / 合并 / tag / Release | 以 GitHub 实际状态为准；发布后独立回读确认。 |

## 正式发布约定

本次属于显示与滚动 bug 修复，风险 `R2`：改变卡片布局及导入模板，有真实设备差异风险；未修改学习来源数据库，也不新增调度器。PR 标记为 `type:bug`、`risk:R2`、`release`，未运行的 iPhone 设备检查保留为 `needs-manual-test`。

1. 推送发布分支并创建 PR；两项必需检查 `test (3.11)`、`test (3.13)` 均通过，基础分支保持最新，独立审查实际 diff。
2. 按 [AGENTS.md](../AGENTS.md) 在当前对话取得维护者对**这个 PR**的明确合并同意。一般发布授权不替代逐 PR 同意，不提前开启 auto-merge。
3. 核对同意所覆盖的 diff 与实时保护，再合并到 `main`。
4. 在合并提交创建 annotated tag `v3.0.1`，正式 Release 设置 `draft=false`、`prerelease=false`。
5. 只上传上述 APKG；截图、说明和核验 JSON 留在源码仓库。GitHub 自动生成的源码归档不属于手工附加文件。
6. 独立回读 tag、Release 状态、附件数量/大小/SHA-256，以及 GitHub 的 MIT 识别后才报告发布完成。

[MIT License](../LICENSE) 继续适用于本项目原创代码和文档，第三方词典、词源、词表、真题、音频与依赖沿用各自授权。本轮不修改配套 exam-library、不上传 AnkiWeb、不重写或删除旧 tag / Release。

## 回退与验证命令

源码回退通过新的 PR；已经发布的 tag 和附件保留不移动。真实集合回退使用 Anki 自身备份，重新导入旧 APKG 不保证撤回全部字段或模板更新。

```bash
uv sync --frozen --extra dev
uv run python -m unittest discover -s tests -v
uv run python scripts/verify_project.py
npm ci
npm run check
npm test
uv build --wheel

# 下载本次 APKG 后核对；使用绝对下载路径替换文件名也可
shasum -a 256 Anki-2027-LiuXiaoyan-Ebbinghaus-v3.0.1.apkg
```
