# 考研英语 Anki 卡包：2026/2027 红宝书、刘晓艳词汇与真题例句

提供 **2026、2027 考研英语红宝书 Anki 单词卡包**，覆盖必考词、基础词、超纲词，并保留 **刘晓艳考研英语词汇艾宾浩斯曲线版**。卡片包含英美音标、离线词典发音、中文释义、词根词缀记忆、双语真题例句、词频与原卷入口；可下载 APKG，使用电脑版 Anki 或 AnkiDroid 学习。本机还提供网页书架、浏览和独立复习。

本页继续保留原有完整功能说明、技术栈、构建命令、数学规则和交互图。源码：[CHNragdoll/anki-pipeline](https://github.com/CHNragdoll/anki-pipeline)；配套真题：[CHNragdoll/exam-library](https://github.com/CHNragdoll/exam-library)。Python 包版本仍为 `3.0.1`；红宝书使用独立日期标签发布。

## 下载 Anki 卡包

红宝书下载入口已更新为 **2026-10-10 手机词根与跳转交互修复版**，刘晓艳保留 **v3.0.1 移动端修复版**。下载后在 Anki / AnkiDroid 中导入 `.apkg`：

| 卡包 | APKG 下载 | 卡片 / 有卡分组 | 真题例句 | 文件大小 | 发布记录 |
|---|---|---:|---:|---:|---|
| 2027考研英语红宝书（必考词+基础词+超纲词）真题例句版 | [2027 完整版 · 手机交互修复版](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2027.10.06/2027-RedBook-Full-Mobile-Interaction-Fixed-20261010.apkg) | 6,530 / 82 | 140,686 | 187.3 MB | [2027 Release](https://github.com/CHNragdoll/anki-pipeline/releases/tag/redbook-2027.10.06) · [交付与来源](docs/REDBOOK_2027.md) |
| 2026考研英语词汇红宝书考研英语（必考词+基础词+超纲词）真题例句版 | [2026 完整版 · 手机交互修复版](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2026.10.06/2026-RedBook-Full-Mobile-Interaction-Fixed-20261010.apkg) | 6,680 / 83 | 141,706 | 188.3 MB | [2026 Release](https://github.com/CHNragdoll/anki-pipeline/releases/tag/redbook-2026.10.06) |
| 27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版 · v3.0.1 移动端修复版 | [刘晓艳移动端修复版](https://github.com/CHNragdoll/anki-pipeline/releases/download/v3.0.1/2027-LiuXiaoyan-English-Vocabulary-Mobile-Fixed-v3.0.1.apkg) | 1,960 / 41 | 20,178 | 85.8 MB | [v3.0.1 Release](https://github.com/CHNragdoll/anki-pipeline/releases/tag/v3.0.1) · [核验记录](docs/RELEASE_3_0_1.md) |

红宝书卡数各包含 **1 张牌组说明卡**；“分组”计有卡子牌组，不计空父牌组。同一句可出现在多个词卡中，例句数是卡片显示合计。MB 按十进制计算。两个红宝书发布附件的明确口音录音缺口均为 **英式 0、美式 0**，引用媒体缺失为 0；这项包内审计不等于逐词听音或全部手机验收。

[v3.0.0](https://github.com/CHNragdoll/anki-pipeline/releases/tag/v3.0.0) 存在移动端显示与滚动问题，已弃用，保留历史记录；请选择 v3.0.1。2026 与 2027 红宝书是独立发布包，不覆盖刘晓艳附件。全部版本见 [Releases](https://github.com/CHNragdoll/anki-pipeline/releases)。

更新已有牌组前先备份集合。学习进度和复习调度由客户端管理；APKG 的压缩文件大小与 AnkiWeb 对整个集合的未压缩大小限制是两回事，导入完整版不保证账户可同步。需要精简范围时可只导出 `00 牌组说明` 与 `01 必考词`，见 [按分组导出](docs/REDBOOK_EXPORT.md#只导出说明和必考词)。

红宝书最新完整包内置按音源调整响度的播放规则，原始录音不重编码；不能启用 Web Audio 或调整播放速度时保留普通播放。历史包可在各自 Release 的 Assets 中下载，精简版不再跟随此次更新。

## 红宝书当前功能与来源

- **原书顺序和目录：** `00 牌组说明` 在最前，随后为必考词、基础词、超纲词 A–Z。词卡按原书顺序连续编号；27 版开头为 `radiate`、`radiant`、`radical`、`object`。基础词 Unit 31 在 `a/an` 处分成“简单基础词之一”和“简单基础词之二”；界面去掉 A/B 前缀，内部 `01/02` 保持目录顺序。
- **英美发音独立选择：** 蓝色 BrE / 红色 NAmE 图标分别播放本地录音，正反面共用选择。英式可选剑桥、牛津；美式可选韦氏、牛津。韦氏缺少本词美音时，使用同词牛津美音并在卡片下方明示回退，仍保留用户的韦氏选择。
- **音标来源：** 英音优先本地剑桥 CALD4，缺失或错配查剑桥英汉简体；美音优先 CACD，再查剑桥基础美式英语、牛津美式英语，最后回退 CALD4。其他缺项保留核对后的补充来源。音标与录音分别记录，不能从音频按钮的词典名推断音标也来自该词典。
- **真实录音与本地复用：** 优先各词典本地资源，再核对相应官网；剑桥、牛津、韦氏及 Collins、Wiktionary、Forvo 的补充录音按词头、来源和口音绑定。27 版最后 11 处补录来自 OED 与本地牛津高阶，26 版复用了其中 4 处。下载资源进入共享本地索引，后续词书可复用。未用相近词录音或合成语音填补这些缺口。
- **释义、词根和例句：** 保留完整中文义项；红宝书释义缺项与错配核对本地及在线牛津、韦氏、剑桥、Collins，并显示补充来源。词根记忆使用虚线列表、折叠箭头、灰底例句和蓝色目标词；保留原文、顺序、链接和换行。双语真题例句、词频、考试标签及原卷跳转继续提供。
- **网页浏览与独立复习：** 本机 [localhost:8771](http://localhost:8771/) 书架包含三套书，可浏览或进入独立复习。搜索结果保留原书顺序，输入完整 `water` 会打开 `water`。网页复习进度独立保存，不读写电脑 Anki，也不连接 AnkiWeb。该服务是本地部署，GitHub Release 提供 APKG；源码 CLI 的静态网页导出与本地复习服务需区分。

详细协议、释义修正绑定、精简导出与适用边界见 [REDBOOK_EXPORT.md](docs/REDBOOK_EXPORT.md)；网页入口说明见 [WEB_LIBRARY_PREVIEW.md](docs/WEB_LIBRARY_PREVIEW.md)。

## 2026-10-10 华为真机与电脑版证据

本轮在 **华为 OCE-AN10 / Android 12 / AnkiDroid 2.20.1** 导入独立三卡测试包，实际操作 `confine`、`radiate`、`apple`：竖线可见；箭头展开、收起不会误触评分；无例句项显示普通圆点；首条有例句项保留箭头；英美音源可独立切换，点扬声器不翻面；读卷菜单可切换；长卡滚动和英中 chunk 点击高亮可用。

两份完整版均已在隔离 Anki 集合中通过原包、覆盖更新、重复导入，保留内容、身份及测试学习记录，媒体引用缺失 0。华为原有 1,960 张卡及 5 条复习记录保持一致；仅新增 3 张测试卡和 2 条测试评分。**三卡真机检查与完整包导入检查是两个范围，没有宣称完整版已逐卡在手机验收。**

| 华为：竖线与展开例句 | 华为：收起后不评分 | 华为：无例句普通圆点 |
|---|---|---|
| ![final 展开，浅色竖线可见](assets/screenshots/readme-20261010/huawei-confine-expanded.png) | ![final 收起，卡数未改变](assets/screenshots/readme-20261010/huawei-confine-collapsed.png) | ![apple 无例句短语无箭头](assets/screenshots/readme-20261010/huawei-apple-no-example.png) |

| 华为：首条折叠箭头 | 华为：英中 chunk 高亮 | 华为：读卷原生菜单 |
|---|---|---|
| ![apple 首条有例句项箭头](assets/screenshots/readme-20261010/huawei-apple-first-arrow.png) | ![双语 chunk 点击高亮与长卡末尾](assets/screenshots/readme-20261010/huawei-chunk-highlight.png) | ![LaTeX 重排与整卷版菜单](assets/screenshots/readme-20261010/huawei-reader-menu.png) |

![电脑版：2027 正式本地浏览页 apple 背面与词根记忆](assets/screenshots/readme-20261010/web-2027-root-memory.png)

![电脑版：2026 正式本地浏览页 apple 背面与词根记忆](assets/screenshots/readme-20261010/web-2026-root-memory.png)

**核验边界：** radiate 首次加载曾出现一次样式资源加载失败，重新进入后正常，原因尚未确定。原卷入口打开了浏览器，但配套 `localhost:8765` 服务不可用，目标定位未验收；欧路外部启动未确认；发音点击可派发播放，未独立听音验收。完整操作、全部 9 张华为截图、异常和数据核对见 [本次核验记录](docs/MOBILE_INTERACTION_EVIDENCE_20261010.md)、[机器可读结果](docs/MOBILE_INTERACTION_VERIFICATION_20261010.json) 和 [截图清单](assets/screenshots/readme-20261010/capture-manifest.json)。

## 2026-10-06 实际界面证据

以下图片来自实际界面操作。华为为 **OCE-AN10，Android 12 / API 31，AnkiDroid 2.20.1**；手机新截图来自现有刘晓艳牌组的浏览器预览，不评分、不导入、不手动同步，不能据此宣称最新红宝书已经在该手机验收。桌面网页截图来自本机服务，27 版网页资源版本目录以对应已发布 APKG 的 SHA-256 命名。截图证明可见内容与布局，声音、外部应用跳转和集合同步需要单独检查。

| 华为：现有刘晓艳牌组正面 | 华为：现有刘晓艳牌组背面 | 华为：向下滚动后的词根内容 |
|---|---|---|
| ![华为 AnkiDroid 现有 action 正面](assets/screenshots/readme-20261006/huawei-liu-existing-front.png) | ![华为 AnkiDroid 现有 action 背面](assets/screenshots/readme-20261006/huawei-liu-existing-answer.png) | ![华为 AnkiDroid 现有 action 词根与派生词](assets/screenshots/readme-20261006/huawei-liu-existing-roots.png) |

![电脑版本机书架：三套词书、浏览、独立学习和卡包下载入口](assets/screenshots/readme-20261006/web-bookshelf.jpg)

![电脑版网页：搜索 water 保持结果顺序，并打开 water 卡片](assets/screenshots/readme-20261006/web-2026-water-search.jpg)

![电脑版网页：2027 according 独立英美发音及牛津回退标注](assets/screenshots/readme-20261006/web-2027-according-fallback.jpg)

![电脑版网页：2027 apple 词根折叠样式与展开的例句](assets/screenshots/readme-20261006/web-2027-root-memory.jpg)

图片入口、捕获方式、版本范围与 SHA-256 见 [本次证据记录](docs/README_EVIDENCE_20261006.md) 和 [捕获清单](assets/screenshots/readme-20261006/capture-manifest.json)。下方 v3.0.1 真机图片为 2026-10-04 历史证据，原有详细功能图片为 rc.3 历史证据，均保留并注明范围。

## 刘晓艳 v3.0.1：历史移动端修复与真机证据

旧倒计时脚本把文档改成固定视口高度的 flex 布局并隐藏溢出内容。在 AnkiDroid 的复习容器 `body > #content > #qa` 中，卡片区域可能被压缩到零高度，造成正面空白、背面闪一下消失，或者长卡无法上下滑动。单独预览的容器不同，因此可能看起来正常。

新版保持客户端的文档高度和原生滚动，倒计时仍随内容放在最后一条译文右下方。APKG 同时更新正面、背面与 1,960 张笔记 Meta 内的旧脚本；词源、录音、例句和课程分组继续随包提供。

**历史真机证据：** 2026-10-04 在华为 OCE-AN10、Android API 31、AnkiDroid 2.20.1 上实际导入并进入复习，分别检查 Lesson 01–03 的 ambition、embarrass、fare。下图左侧为正面，右侧为背面状态；ambition 背面可看到词源树，再向下滑动可到第 23 条例句和内容末尾。未点击评分按钮。

![华为实际复习：ambition 正面与背面，词源树可见](assets/screenshots/v3.0.1/huawei-ambition-front-answer.png)

![华为实际复习：embarrass 正面与持续显示的背面](assets/screenshots/v3.0.1/huawei-embarrass-front-answer.png)

![华为实际复习：fare 正面与背面](assets/screenshots/v3.0.1/huawei-fare-front-answer.png)

![华为长背面滑到底部：第23条例句、完整翻译和随内容排列的倒计时](assets/screenshots/v3.0.1/huawei-ambition-bottom.png)

**iPhone 范围：** 维护者反馈这版已恢复上下滑动和词根显示；该次直接观察与截图来自华为；2026-10-06 也未新增 iPhone / AnkiMobile 真机验收。截图出处与 SHA-256 见 [本次捕获清单](assets/screenshots/v3.0.1/capture-manifest.json)。完整功能、技术栈、逐步命令、数学模型、交互和 Mermaid 图继续保留在下文。

## 1. 项目做什么、怎么做

### 1.1 项目要解决的问题

这个项目把词表、词典、词源和历年真题整理成可复习的 Anki 卡片，同时提供同内容的网页预览。学习时可以先认单词和音标，再翻面查看释义、词形、词源、考试标签、词频和真题中的实际用法；遇到想进一步阅读的例句，可跳到真题仓库查看完整题目或文章。

它也为维护者提供一条可恢复的资料处理流程：从旧资料迁移到独立的新数据库，按稳定 ID 导出和回填译文，校验内容与音频，最后生成 APKG、网页和离线网页 ZIP。生成结果与原始资料分开，原始词表、旧数据库、词典和真题来源保留。

刘晓艳 v3.0.1 的默认卡组名称为 **27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版**。这是卡组的显示名称。本仓库负责内容、模板和打包；复习间隔及评分后的调度由 Anki 客户端负责。仓库没有独立实现一套“艾宾浩斯曲线”调度器，也没有从名称自动启用 Anki 的某种调度参数。

适合两类使用者：

- 学习者：导入已生成的 APKG，或直接打开完整网页预览，查词、翻面、阅读例句、跳到原卷。
- 维护者：核对资料来源、修改人工译文、加入词表或 PDF、验证补全与统计、重新生成产物。

### 1.2 输入、处理中间件与输出

| 层次 | 内容 | 谁负责保存或生成 | 不能混淆的事项 |
|---|---|---|---|
| 旧资料输入 | V2.0 SQLite、Excel 词表、原录音、历史 APKG | 使用者本机保存 | 是只读迁移输入，不是新版写入目标。 |
| 词典输入 | 已解包的牛津、韦氏数据库及录音，ECDICT，词根词缀资料 | 本机外部资源目录 | 原词典内容和许可不因为进入卡包而变成本项目原创。 |
| 真题输入 | `exam-library` 的结构化试卷、句子索引、译文、审校和来源记录 | 配套真题仓库与本机已核验资料 | 最新本地联动文件不能自动视作已在远端发布。 |
| 新版学习状态 | `data/anki.sqlite3` | 本项目 SQLite 存储层 | 保存词卡、原例句、译文、隔离原因与迁移记录；不是真实 Anki 用户集合。 |
| 已审补全输入 | 阅读题干补全、选项组合译文及其审校侧车 | 本机版本化 JSON 与审校证据 | 补全是派生内容，不覆盖原题干；缺少对应审校文件不能凭空重建。 |
| 派生展示 | 牛津完整释义、韦氏词形、词源、真题例句、词频及链接 | 内存中的构建过程 | 构建时读取并组合，不把这些展示修改写回原资料。 |
| Anki 输出 | `.apkg`，包含笔记、模板及本地媒体 | `packaging.py` | 包可以导入 Anki，但包本身不等于用户的复习进度备份。 |
| 网页输出 | `preview.html`、全卡组 `preview-library.html`、目录与共享媒体 | `web_preview.py` | 此 CLI 导出静态预览，不包含评分、排程或 Anki 同步；另见上方本机独立复习入口。 |
| 离线网页输出 | `Anki-完整网页预览.zip` | `web_bundle.py` | 解压后可独立阅读词卡；原卷跳转仍需另外启动真题服务。 |
| 证据输出 | 构建报告、质量报告、导入核验、截图 | 命令与实际验收 | 机器校验、真实界面截图和人工语义审校分别回答不同问题。 |

源码证据：`anki_pipeline/cli.py`、`config.py`、`store.py`、`exam_library.py`、`packaging.py`、`web_preview.py`、`web_bundle.py`。

### 1.3 刘晓艳 v3.0.1 构建快照怎么读

以下是刘晓艳词库本地完整生成报告的快照，而不是承诺以后每次构建都固定这些数量。输入、排除规则、有效译文和词形来源变化后，应以新的构建报告为准。

| 项目 | 本地快照 | 计量含义 |
|---|---:|---|
| 词卡 | 1,960 张 | 不是 1,960 个不同的真题词句。 |
| Unit / Lesson 分组 | 41 个 | 保留原课程层次，也保留源数据中的特殊分组。 |
| 卡片中显示的真题例句 | 20,178 条 | 按词卡合计；同一句可属于多个不同词卡。 |
| 打包录音 | 6,530 个媒体文件 | 包含真实词典录音；不是每张卡恰好只有一个媒体文件。 |
| 考研英语语料 | 44 套，2000–2026 年 | 不等于真题仓库所有科目的资料数量。 |
| 审校索引中的原始句子记录 | 17,755 条 | 未做显示与印刷来源规范去重前的记录数。 |
| 规范去重后的来源句子 | 16,065 条 | 用于原始来源计数；与显示例句数量不同。 |
| 双向补全合并掉的正确选项例句 | 608 条 | 同题同组合的正确选项与题干显示合并；不减少真实印刷出现次数。 |
| 没有可显示题库例句的词卡 | 249 张 | 基础词卡仍保留；不能为了有例句而造句或删词。 |
| 全部词卡的来源命中次数合计 | 21,537 次 | 跨词卡的合计，不是语料中不同 token 的数量。 |

证据：本机生成的 `output/web-preview-report.json` 和 `output/dictionary-delivery-report.json`。`data/` 与 `output/` 属于本地输入或生成目录，通常不纳入源码 Git 历史。历史 README 和早期功能记录里的 14,446、14,565、20,006 等数量对应当时的输入版本，不能替代这一快照。

### 1.4 阅读代码时先看哪些目录

```text
anki_rebuild/
├── config.toml                 路径、卡组和资料来源配置
├── pyproject.toml / uv.lock     Python 包与锁定依赖
├── anki_pipeline/
│   ├── cli.py / config.py      命令入口及路径保护
│   ├── store.py                SQLite 表、事务、备份、恢复
│   ├── migration.py            旧 V2.0 只读迁移
│   ├── inputs.py / pdf.py      Excel、可选词典联网、PDF 输入
│   ├── text.py / forms.py      文本和显式词形处理
│   ├── local_dictionary.py     牛津 / 韦氏内容及录音
│   ├── ecdict.py               明确数据补缺和考试标签
│   ├── etymology.py            原始词源查看器的离线适配
│   ├── codex_exam_index.py     审校句子索引验证
│   ├── reading_completion.py   题干 + 正确选项补全
│   ├── option_context.py       选项 + 题干上下文
│   ├── option_translation.py   组合译文及审校绑定
│   ├── sentence_insertion.py   Part B 句子插入
│   ├── occurrence_exclusions.py  已审同形异义排除
│   ├── exam_frequency.py       原位置词频与半星
│   ├── source_paths.py         人能读懂的来源层级
│   ├── translation_alignment.py  现成双语范围验证
│   ├── exam_library.py         真题资料聚合、去重、链接
│   ├── packaging.py           Anki 模型、字段与安全打包
│   ├── web_preview.py / web_bundle.py  全库网页及 ZIP
│   └── templates/             HTML、CSS 和各交互脚本
├── scripts/                   导入、词频、补全等核验工具
├── tests/                     Python 与 Node 回归测试
├── docs/                      专项说明与历史验收
├── assets/screenshots/         rc.3、v3.0.1 与 readme-20261006 分期证据
├── data/                      本机新库、音频和已审侧车
├── output/                    APKG、网页、ZIP 与报告
└── backups/                   数据库与本地恢复材料
```

结构上是一个 Python 包加原生网页模板，不是多个线上微服务。完整词典资料和真题仓库是外部输入，不隐藏在 Python wheel 中。

### 1.5 Anki 卡片的全部学习功能与操作

#### 1.5.1 正面：认词、音标、查词和真实录音

本节及下图记录刘晓艳 v3.0.1 的单来源选择模板；红宝书的独立英美控件见上方当前功能与新截图。正面显示单词、可用音标和播放按钮。左上角“发音”选择器选择牛津或韦氏，右上角保留 Unit / Lesson / 位置。正反面使用同一头部布局，发音选择器不会在正面挤到单词下面。

播放图标保留三角形外的一圈细线。去掉的是图标外层按钮的额外边框、底色和阴影；键盘焦点提示仍保留。单词在卡片内容区域独立居中，右侧查词图标不参与单词的中心计算。

| 操作 | 结果 | 来源或限制 |
|---|---|---|
| 点击“发音”选择器 | 切换该词的录音来源，并保存来源偏好 | `templates/script.js`；有实际缺口时只使用已声明的另一个来源回退。 |
| 点击播放圆圈 | 播放包内已保存的 MP3 | 不需要 8770 词典 API；实际发音来源可与请求来源不同，回退会明示。 |
| 点击单词右侧放大镜 | 按原来的 `eudic://` 协议调用欧路查词 | 需要操作系统安装并注册欧路；网页截图不能证明每台机器都注册了协议。 |
| 翻面 | 显示背面释义、词源和例句 | Anki 的“显示答案”属于客户端；网页有自己的翻面按钮。 |

录音只使用实际来源，不能拿其他单词的录音填空。完整构建目前没有无音频词卡，这是一项本地快照，不是读取新词表时自动保证。

![新卡组名、目录、正面发音选择与圆形播放按钮](assets/screenshots/v3.0.0-rc.3/card-front.jpg)

![背面发音位置、真题词频、半星与牛津释义](assets/screenshots/v3.0.0-rc.3/card-back-overview.jpg)

![全局发音改为韦氏，前后面共用选择](assets/screenshots/v3.0.0-rc.3/card-pronunciation.jpg)

#### 1.5.2 背面：完整释义、词形、派生词和考试标签

背面采用完整牛津中文义项，不为了缩短卡片截掉后面的义项。词性和义项分行；韦氏的词形变化与派生词分别呈现，桌面上可使用两列，窄屏自然换行。

以下记录通用 CLI / 历史刘晓艳资料的缺项规则；红宝书发布包另外核对了在线词典补项，不以 ECDICT 代替已找到的词典释义。数据优先级是“对应整栏是否缺失”，不是把多个来源随意拼成一段：

- 牛津有中文义项，保留完整牛津义项；整个中文义项缺失，才使用明确 ECDICT 中文数据并标注来源。
- 韦氏有词形变化，使用韦氏记录；整个词形栏缺失，才使用经核查的 ECDICT 屈折形式。
- 派生词与屈折变化分开；ECDICT 没有明确派生关系时不凭拼写猜造派生词。
- 考试标签来自 ECDICT `tag`；没有标签明确显示未标注。
- 已有韦氏词形不会与旧词表的另一套词形自动混合。派生词也不会因为出现在词形区域就自动进入目标词例句匹配。

`exsert` 是资料补缺的具体例子：牛津缺失时使用 ECDICT 中文，并显示对应来源；声音使用包中确实存在的来源。`means` 的父词 `mean` 可能有 `meaning`、`meant` 等变化，这些变化没有本卡的归属证据时，不能计入 `means` 的目标匹配。

![词形变化、派生词与词族](assets/screenshots/v3.0.0-rc.3/card-forms.jpg)

![历史刘晓艳模板：exsert 缺牛津释义时使用 ECDICT，零词频、无真题例句如实显示](assets/screenshots/v3.0.0-rc.3/card-ecdict-fallback.jpg)

#### 1.5.3 词根与词源：保留原内容、树形展开和词根折叠列表

红宝书的词根记忆列表另有灰底例句与折叠箭头样式，见上方 apple 实际截图；以下原树形词源交互继续保留。词源区域位于考试标签之后，使用原词源查看器的正文、树形节点、根词、词缀、解释、同根词、派生词和双语例句。加减号、叶节点圆点、虚线连接及原例句图标保留；适配仅调整外部卡片所需的字号、行高、换行和高度。

操作方式包括：展开或收起树节点、展开某个关联词的例句，以及整批展开 / 收起。词源中已有查词链接继续使用原行为。例句不额外重复“翻译”前缀，词源标签不添加多余 `#`。

词源在独立 `sandbox` iframe 中运行。内容自动增高，随外层卡片阅读区域滚动；不另开一个小滚动框挤住正文。树展开后，父窗口收到来自该 iframe 的高度消息，再调整 iframe 高度。

![词源的初始状态：保留原树形节点、查词协议与展开/收起例句入口](assets/screenshots/v3.0.0-rc.3/card-etymology-collapsed.jpg)

![原词源树、词根词缀、同根词及展开例句](assets/screenshots/v3.0.0-rc.3/card-etymology.jpg)

#### 1.5.4 真题例句、完整译文和英文目标词

例句展示整句英文、现成逐句译文及可读的来源路径。目标词及词典明确记录的屈折变化使用相同的匹配规则；在恢复出来的题干与原选项中都能标记目标词。中文初始保持普通文字，不把相似中文自动当成单词对译。

启用真题库配置时，`max_examples = 0` 表示显示该词全部可用的题库例句。它不同于 `[deck].max_examples` 的旧库示例上限。没有有效译文或来源绑定时不静默补造内容。裸词选项可以计入印刷词频，但不单独生成一句孤零零的“例句”。

长例句正常换行。题干和候选项已经组合成一句时，不应在中间再留一个多余的大空段；没有填空的问句与选项则保留明确的分段，让两者关系可读。

![完整双语真题例句与来源层级](assets/screenshots/v3.0.0-rc.3/card-examples.jpg)

![点击前：选项D补题干并保留下划线，中文已拼接](assets/screenshots/v3.0.0-rc.3/jump-option-before.jpg)

#### 1.5.5 完形、阅读题干、阅读选项与 Part B 补全

这些补全解决“卡片只剩半句或一个选项，看不懂上下文”的问题。原卷内容保持原样，卡片里显示的是有来源绑定的派生组合。

| 情况 | 卡片怎么显示 | 答案与下划线 | 不应产生的误解 |
|---|---|---|---|
| 完形填空 | 先使用明确正确答案回填，再逐句匹配 | 插入答案有下划线 | 回填文本不额外增加原卷词频。 |
| 阅读题干有一个空位 | 题干 + 明确正确选项 | 插入正确选项有下划线 | 没有可信答案时不能猜选项。 |
| 例句来自阅读选项 | 将完整题干补回；有空位则插入当前候选项 | 当前候选项有下划线，来源显示 A / B / C / D | B / C / D 候选项不是因为成为完整句就变成正确答案。 |
| 阅读题干没有空位 | 原问题与当前候选项分段显示 | 不虚构填空位置 | 问题和选项仍保留各自原文字义。 |
| Part B 句子插入 | 按明确答案组合原段与对应选项 | 插入范围有下划线 | 原选项和原段的来源坐标分开保存。 |
| 正确选项和题干双向都得到同一组合 | 同题、同完整文本的显示例句合为一条 | 保留原来的插入下划线 | 合并显示不合并两个实际印刷位置的词频。 |

中文显示经过审校的完整译文，而不是“题干：……[选项 A] / 选项 A：……”的临时拼接格式。候选项组合的独立译文与审校侧车按哈希绑定；已经批准后再改文字，需要重新审校。

![dominate 的实际卡片：完形答案 Still 已回填，下划线保留，目标 dominating 标记](assets/screenshots/v3.0.0-rc.3/card-cloze-completion.jpg)

![点击前：双向补全合并为一条例句，题干与正确选项C](assets/screenshots/v3.0.0-rc.3/jump-twoway-before.jpg)

![margin 的实际 Part B 句子插入：2008 第43题正确句子回填并加下划线，原段与完整译文一起展示](assets/screenshots/v3.0.0-rc.3/card-sentence-insertion.jpg)


#### 翻译生成、交叉验证与 chunk 划分

维护者确认的项目生成说明：**翻译均由 GPT-6.1 Sol Xhigh 生成，并进行交叉验证、划分 chunk。** 生成与独立审校分开执行；完整译文和双语片段范围绑定原句 ID、原文 hash 与审校内容 hash，供英文或中文悬浮/点击时展示对应。

模型规格是维护者的生成声明；保留的审校文件及 hash 用于核对内容和证据链，不将文件哈希当作历史每次运行模型设置的证明。现成 chunk 的覆盖和已知语义偏差仍按 3.8 说明，不宣称每个位置已全部无误。

#### 1.5.6 英文和中文都能触发对应荧光，手机也能点击

有现成有效 chunk 对应索引的例句，英文与中文都可以作为入口。荧光色统一为 **`#ffe69b`**，对应范围同时显示该颜色。这个动作显示已有对应关系，不在鼠标悬停时临时翻译或模糊猜测。

| 交互 | 具体行为 |
|---|---|
| 鼠标放在英文对应片段上 | 当前例句的英文和中文对应片段同时荧光显示。 |
| 鼠标放在中文对应片段上 | 也显示已有对应的中英文；中文片段可以关联多个已确认的英文 chunk。 |
| 点击英文或中文片段 | 固定当前对应，适用于手机和平板。 |
| 再点击同一个对应 | 取消固定荧光。 |
| 点击空白或按 Esc | 取消当前对应。 |
| 移到另一条例句 | 不把上一条例句的 chunk ID 扩散到其他例句。 |
| 点击链接、音频或表单控件 | 保留控件原来的动作，不能被 chunk 点击劫持。 |

没有有效对齐的数据仍保持普通文字；不会使用整个译文作为万能对应。技术校验验证范围、哈希和结构，不能替代语言上的准确性审查。已有对齐覆盖并不是 100%，个别语义对应仍需继续核验。

[查看同屏证据：完整双语真题例句与来源层级](assets/screenshots/v3.0.0-rc.3/card-examples.jpg)

![点击英文 many，中文很多同步使用相同荧光色](assets/screenshots/v3.0.0-rc.3/card-chunk-english.jpg)

![点击中文当作理想，英文 as an ideal 同时荧光显示](assets/screenshots/v3.0.0-rc.3/card-chunk-chinese.jpg)

#### 1.5.7 原句跳转：完整路径、题目顶部和外框

例句下方的出处按原卷真实层级显示，例如：

```text
2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Part A ➫ Text 5 ➫ 第28题 ➫ 选项C
```

这里的 `➫` 是显示分隔符。内部 `kaoyan:...:q-...` ID 保留给程序定位，不应直接显示成只有年份或难读的一段程序路径。

在例句栏选择“跳转到 LaTeX 重排”或“整卷版”，再点对应例句右上角跳转图标。程序根据句子 ID、英文哈希、审校内容哈希和原位置范围确认目标；读者看到的是原题 / 原文，不是将完整卡片复制到真题页。

定位原则：

- 来自选项的例句仍跳到所属题；题干顶部进入可见区，方便连题干一起读，不把最后一个选项单独顶到页面顶部。
- 已定位的句子或对应选项加外框，帮助看清位置；不另外给某一个目标单词留固定黄色标记。
- **只有合并后的双向补全**额外携带两组来源引用，同时框出题干和对应正确选项。普通单向补全仍保留其原来单一目标的行为。
- 跨行原句的框应沿同一个文本块的实际行范围绘制；不同物理块不能被一个覆盖无关文字的大矩形随意串起来。
- 哈希失配、来源缺失或输入过期时，应显示失败或拒绝定位；不能在卷中找个相似词当成功。

下面的证据需要成对看：点击前能看到选中的例句与来源，点击后能看到所属题、原始空位和正确选项都保持原文。

[查看同屏证据：点击前：选项D补题干并保留下划线，中文已拼接](assets/screenshots/v3.0.0-rc.3/jump-option-before.jpg)

![原段落跳转后：319×702 窄屏，来源句子的连续外框与顶部定位](assets/screenshots/v3.0.0-rc.3/jump-passage-after.jpg)

![实际点击普通补全选项D，桌面重载后定位第28题顶部，仅选项外框，无单词单独标记](assets/screenshots/v3.0.0-rc.3/jump-option-after.jpg)

[查看同屏证据：点击前：双向补全合并为一条例句，题干与正确选项C](assets/screenshots/v3.0.0-rc.3/jump-twoway-before.jpg)

![实际点击双向補全链接，桌面重载后题干顶部定位，题干和选项C同时框选](assets/screenshots/v3.0.0-rc.3/jump-twoway-after.jpg)

#### 1.5.8 真题词频、覆盖试卷和半星

词频区同时显示“出现次数”“覆盖了多少套 / 总共多少套”和 0–5 的半星等级。例句右侧的序号只表示卡片中第几条展示例句；它不是词频。

例如 `ambition` 的本地快照是 **27 次，覆盖 9 / 44 套，3.5 / 5**。同一句里出现三次就计三次，多个词卡共用同一句也分别统计；但把一个选项复制进题干不会增加一次。

详细公式、原始位置与双向补全计数见第 3 章。

[查看同屏证据：背面发音位置、真题词频、半星与牛津释义](assets/screenshots/v3.0.0-rc.3/card-back-overview.jpg)

#### 1.5.9 倒计时、正反面切换和内容滚动

倒计时放在真题例句 / 翻译内容结束处的右下方，跟着该内容一起滚动。它不是固定在整个窗口右下角的悬浮栏，因此不会在背面顶部遮住释义，也不会为窗口底部额外留一条空白带。

正面或没有例句的卡片使用对应内容末尾作为回退位置。翻面、切卡或 Anki 复用 WebView 时，脚本清除旧定时器和旧包装，重新确认当前内容节点；不能因为上一张卡的 body class 留下而把新正面隐藏。

倒计时目标在源码中固定为 `2026-12-19T08:30:00+08:00`，显示“2027 考研倒计时”。这是模板中的配置目标，不是实时查询的官方考试日历；需要更新日期时修改模板并重新生成。时间到后显示“2027 考研初试已开始”。

[查看同屏证据：背面发音位置、真题词频、半星与牛津释义](assets/screenshots/v3.0.0-rc.3/card-back-overview.jpg)

![倒计时跟随卡片内容末尾右对齐，不占用页面固定底栏](assets/screenshots/v3.0.0-rc.3/card-content-end-countdown.jpg)

### 1.6 完整网页预览的全部功能

网页沿用 Anki 的内容与模板，提供更方便的全库浏览入口。本节描述 CLI 导出的静态预览。本机另有独立网页复习服务，见首页入口与专项说明；两者都不与 Anki 集合同步。

| 功能 | 怎么使用 | 结果与边界 |
|---|---|---|
| 卡组目录 | 点击 Unit / Lesson 或全部卡组 | 按实际来源分组，不创造没有的课程。 |
| 单词和释义搜索 | 在左侧搜索框输入 | 在当前目录范围查找；没有结果显示空状态，清空后恢复。 |
| 选择词卡 | 点击列表中的词条 | 右侧加载该卡，列表与序号同步。 |
| 正反面 | 点击“显示答案 / 返回正面”，或按空格 | 使用同一词卡的正反面，不进行 Anki 评分。 |
| 前后张 | 点击按钮，或按左右箭头 | 切到当前筛选结果中的相邻卡片；在输入框打字时不拦截这些按键。 |
| 刷新恢复 | 刷新当前地址 | 地址保存卡片 / 卡组位置；发音和原卷版本偏好另有本地保存。 |
| 手机目录 | 点击“目录” | 窄窗口打开抽屉目录，避免三栏挤在一起。 |
| 媒体共享 | 正常播放词卡 | 音频文件在版本目录共享，不在每张 HTML 中重复塞入同一个录音。 |
| 出错状态 | 缺少某张文件或加载失败时 | 保留明确错误状态，不能显示上张卡却把列表位置改成新卡。 |
| 离线 ZIP | 解压后启动包内服务 | 词卡、词典和录音不依赖原数据库或 8770；原卷仍是单独服务。 |

Safari 首次加载需先给 iframe 一个确定的布局尺寸，再设置导航地址；不能在 `display:none` 的零尺寸容器里初始化后，指望用户改变窗口大小才正常。词卡正文正常换行，不通过剪掉内容消除溢出。

[查看同屏证据：新卡组名、目录、正面发音选择与圆形播放按钮](assets/screenshots/v3.0.0-rc.3/card-front.jpg)

![Lesson2 内搜索 rise：返回 rise、arise、enterprise，卡组筛选与上下张导航](assets/screenshots/v3.0.0-rc.3/card-deck-search.jpg)

![目录搜索无结果时提供明确提示与清空入口](assets/screenshots/v3.0.0-rc.3/card-empty-search.jpg)

![390×844 手机比例目录抽屉：卡组树、搜索与关闭入口](assets/screenshots/v3.0.0-rc.3/card-mobile-directory.jpg)

> 历史证据，保留此前运行状态；不是本轮重新捕获。

![历史运行证据：local-dictionary-portable-humour](assets/screenshots/v3.0.0-rc.3/historical-local-dictionary-portable-humour.png)

### 1.7 配套真题仓库的全部使用入口与交互

真题阅读和练习由独立仓库 [CHNragdoll/exam-library](https://github.com/CHNragdoll/exam-library) 提供。Anki 项目配置其本机目录和服务地址，从它的核验输入生成例句及跳转链接。

本地总目录快照有 **335 份资料、8 个科目、670 个原版 / 重排阅读版本**；其中考研英语 44 份。资料包括题卷与实际存在的答案卷，不保证每年每科都同时有题卷和答案卷。整卷练习目录的数量与原版 / 重排阅读版本的数量属于不同维度。

重要发布边界：这份说明既介绍已经存在的真题阅读功能，也介绍当前本机联动。部分最新句子定位、逐句审校索引、chunk 对应、重绘首屏修复和版式修改仍位于配套仓库的本地工作区；不能把它们描述成 `exam-library` 远端 `0.1.0` 已经包含的发布内容。更新另一台机器时，必须同时确认配套代码和所需索引的版本。

#### 1.7.1 总目录、筛选、原版、重排和并排

总目录从 `http://localhost:8765/` 进入。可以按科目、年份、卷种搜索筛选，查看最近阅读，并打开同一份资料的不同阅读版本。

| 模式或控件 | 用途 | 保留的语义 |
|---|---|---|
| SVG 原版 | 按原稿页面版式阅读 | 公式、图形和原页面位置优先；转录与原稿核对的重要入口。 |
| LaTeX 重排 | 文字随窗口宽度重新排版，可选中复制 | 内容不因为排版改变而自动增删。 |
| 并排对比 | 同一资料两版同窗显示，分别滚动 | 桌面并排，窄屏可上下排列；不是两个不同试卷。 |
| 目录 | 跳到对应章节 / 材料 | 以原卷层级组织，不只列年份。 |
| 阅读设置 | 调字号、阅读宽度；原版可缩放 | 设置与内容分开。 |
| 专注阅读 | 收起妨碍阅读的导航 | 阅读状态仍可退出。 |
| 回到开头 | 回到当前资料开头 | “显示审校译文”放在同一工具栏附近，便于找到。 |
| 阅读进度与最近阅读 | 记录本机浏览器最近位置 | 存在该站点的浏览器本地状态；不等同于 Anki 同步。 |

![真题书架、八科目分类、阅读记录与版本入口](assets/screenshots/v3.0.0-rc.3/exam-catalog.jpg)

![同卷SVG原版与LaTeX重排并排阅读](assets/screenshots/v3.0.0-rc.3/exam-parallel.jpg)

![LaTeX重排、目录、阅读工具、可下载源码](assets/screenshots/v3.0.0-rc.3/exam-reflow.jpg)

[查看同屏证据：同卷SVG原版与LaTeX重排并排阅读](assets/screenshots/v3.0.0-rc.3/exam-parallel.jpg)

![展开阅读设置，字号和宽度保存在本机](assets/screenshots/v3.0.0-rc.3/exam-reading-settings.jpg)

#### 1.7.2 译文、chunk 和原卷定位

有已发布到本机静态目录的审校译文时，阅读器可显示段落 / 句子的中文；英文与中文对应使用现成索引。显示开关只改变阅读状态，不把中文写回原卷。深链接需要原句 ID、英文哈希和审校内容哈希都一致，才能使用对应范围。

原版和重排是两种不同渲染：原版还要处理页面 SVG 的文字和跨行框；重排按页面 DOM 定位。卡片 → 原卷的点击前后证据已经放在 1.5.7；不能只用一个直接打开的结果页面证明所有入口都可跳转。

![显示审校译文、空格和中文段落对应](assets/screenshots/v3.0.0-rc.3/exam-reviewed-translation.jpg)

#### 1.7.3 整卷练习：作答、答案与沉浸模式

默认按原卷顺序展示文章、题干、选项和有明确来源的参考答案。题目保留固定 ID；选择顺序或显示字母变化，不应改变答案身份。

| 功能 | 操作与结果 |
|---|---|
| 整卷入口 | 从总目录进入整卷练习，或打开 `full-paper.htm?paper=...`。 |
| 选择选项 | 点击单选 / 多选控件，记录当前界面选择。 |
| 查看答案 | 按题展开可信参考答案、解答或解析。缺失 / 不确定答案不伪装成可判分。 |
| 主观题 | 在输入区记录思路，再查看已存在的答案材料。输入不由 Anki 收集。 |
| 章节目录 | 跳到完形、阅读、Part B、翻译或写作对应区段。 |
| 双栏沉浸模式 | 阅读材料与问题分区，减少在长文章里来回寻找；目录保留当前层级。 |
| 译文开关 | 显示 / 隐藏中文；沉浸模式可点原文或选项查看已有中文。 |
| 直接单题入口 | 单题工具仍保留可访问的直接入口；主目录优先整卷体验。 |
| 选项乱序 | API 支持 `order=shuffle&seed=...`；相同种子可重现，固定选项 ID 不改。是否启用由具体界面入口决定。 |

目前练习 SQLite 只存题文与资料，不持久保存用户作答记录。不要把某次浏览器页面里的选择当成服务器已经保存的复习记录。

![完形四选项一行，译文在右侧，答案按钮右上角](assets/screenshots/v3.0.0-rc.3/exam-cloze-before.jpg)

![选择答案后原位查看参考答案](assets/screenshots/v3.0.0-rc.3/exam-cloze-answer.jpg)

![沉浸式原文与作答三栏](assets/screenshots/v3.0.0-rc.3/exam-immersive.jpg)

#### 1.7.4 不同题型的排版

| 题型 | 排版规则 |
|---|---|
| 完形四选一 | 每题四个选项一行排列；对应中文在选项内右侧，不另塞背景块；查看答案在题目右上角。 |
| 阅读四选一 | 长选项仍能正常换行，题干与选项的译文按阅读结构显示。 |
| Part B 短标题选项库 | A / B、C / D、E / F、G 两列排，避免连成一长段。 |
| 段落排序 | 上方正文已经列出 A–H 段落，作答区只列可选字母；每题五个字母一行，不重复全部段落。 |
| 排序选择按钮 | 圆圈和字母水平排布、居中对齐；查看答案放题目右上角。 |
| 排序 SVG | 顺序示意图控制展示尺寸，不把整个屏幕撑满。 |
| 写作图片 | 原图 / 重绘图都可查看，题干与写作要求保留；图片自身尺寸与作答区分开。 |

[查看同屏证据：完形四选项一行，译文在右侧，答案按钮右上角](assets/screenshots/v3.0.0-rc.3/exam-cloze-before.jpg)

![2018 年英语二 Part B：七个短标题按 A/B、C/D、E/F、G 两列排列](assets/screenshots/v3.0.0-rc.3/exam-short-headings.jpg)

![排序题五字母选项同一行、右上角答案与缩小顺序图](assets/screenshots/v3.0.0-rc.3/exam-ordering.jpg)

#### 1.7.5 原图、重绘图和裁切审阅

认可的重绘图片通过映射表绑定原图。首次打开时，新图确实加载成功后才切换显示；等待期间仍保留原图。不能把重绘图先隐藏又 `loading=lazy`，导致它一直等待进入可见范围，最后必须手动切换两遍才能正确显示。

“查看原图 / 查看重绘图”可来回切换。展示宽度在原图和重绘图之间保持一致，避免刚打开时是巨图、切换后才缩到正常尺寸。加载失败仍能读原图，不以图片失效为由隐藏整道题。

另外保留图片审阅与裁切审阅入口，用来比较原图、重绘图、原页位置及裁切边界；维护者可记录状态并导出审阅记录。审阅状态与学习答案无关。

![2000 写作题首次进入，重绘图自动加载并保持小尺寸](assets/screenshots/v3.0.0-rc.3/exam-redraw-first-load.jpg)

![点击查看原图，原卷图片和切换入口](assets/screenshots/v3.0.0-rc.3/exam-redraw-original.jpg)

![实际点击查看原图、再切回重绘图：小尺寸与首次进入一致，不再铺满页面](assets/screenshots/v3.0.0-rc.3/exam-redraw-return.jpg)

![原图与重绘并排审查，结论和备注导出](assets/screenshots/v3.0.0-rc.3/exam-image-audit.jpg)

![旧裁框、新裁框与修复前后原图](assets/screenshots/v3.0.0-rc.3/exam-crop-audit.jpg)

#### 1.7.6 结构化题库和只读 API

真题仓库把原版与重排中的材料、题干、选项、答案、公式、图片和来源块规范化为 JSON / JSONL，再建立本地 SQLite。结构化文件是可移植输入，SQLite 是可重建的读取库。新增语义层描述 paper / section / passage / material / question / option / answer 的结构，以及共享材料、延续块和质量问题。

服务默认仅监听 `127.0.0.1`。它提供读取题目和读取答案的 API，不提供自动把学习结果写回 Anki 的接口。

| API | 作用 |
|---|---|
| `GET /api/v1/meta` | 查看模式版本、卷 / 题 / 选项数量。 |
| `GET /api/v1/papers?category=kaoyan` | 列出该类有题目的试卷。 |
| `GET /api/v1/papers/{paperId}/questions?order=default` | 原卷顺序的题目和选项；尚不返回正确标记。 |
| `GET /api/v1/papers/{paperId}/questions?order=shuffle&seed=demo` | 可重现的选项显示乱序。 |
| `GET /api/v1/questions/{questionId}` | 单题内容。 |
| `GET /api/v1/questions/{questionId}/answer` | 展开答案时取得材料与可信 `correctOptionIds`。 |

证据：配套仓库 `scripts/question_bank_schema.sql`、`build_question_database.py`、`question_database_api.py` 和 `serve_exam_library.py`。固定 ID 与答案三态见第 3 章。语义 API 的具体新增范围以配套仓库当前实现为准，不能把本地工作区代码自动算作本 PR 已交付的远端接口。

![多模板结构化目录和逐卷 JSON](assets/screenshots/v3.0.0-rc.3/exam-structured.jpg)

### 1.8 两个仓库究竟怎样联动

两个方向需要分别理解：

1. **构建时读取资料**：Anki 读取本机 `exam-library` 目录里的结构化真题与已审句子索引，生成卡片内容、来源路径及定位参数。构建本身不需要让 8765 服务一直启动。
2. **学习时点击跳转**：卡片中的链接打开配置的 `base_url`，由 8765 真题服务显示原卷 / 整卷题。此时必须让真题服务可访问。

录音、释义、词源和卡片本身已经打包，不需要 8770 字典服务。8765 的作用是打开真题上下文，不是给卡片返回词义。

```toml
[exam_library]
root = "../exam-library"
base_url = "http://localhost:8765"
reader = "latex"                    # 可改为 "full-paper"
max_examples = 0                    # 0 = 全部可用题库例句
sentence_source = "codex"
codex_index_root = "../exam-library/data/staging/codex-translations-v1"
reading_completion_path = "data/reading-completions-v1.json"
```

配置路径相对于 `config.toml` 所在目录，网页链接地址则是客户端实际访问的地址。如果手机上的 Anki 打开 `localhost:8765`，它指向手机自己，不是家里的 Mac。默认服务也只绑定本机；手机通过网络访问需要另行配置适合的服务地址和监听方式，本仓库没有自动完成远程访问或端口穿透。

`reading_completion_path` 显式指定阅读题补全侧车；未配置时使用项目数据目录内的默认文件。该路径及词典、真题索引路径都需要在换机器后重新核对。已批准的侧车、review 和独立审校证据属于外部内容输入，不随源码提交自动分发。

换机器时需要一起准备：已安装的 Anki 或网页运行环境、卡包 / ZIP，以及要继续使用原卷跳转时所需的真题库服务与相同版本的句子索引。只复制 Anki Python 源码不能从零得到完整第三方资料与私人审校输入。

### 1.9 安装与先做只读检查

以下命令以本机目录为例。另一台机器应替换目录，并先检查 `config.toml`；不要直接套用旧库路径去覆盖自己的资料。

#### 步骤 1：进入仓库

```bash
cd /Users/apple/Documents/PyCharm/Anki/anki_rebuild
```

命令作用：进入包含 `pyproject.toml`、`uv.lock` 和 `config.toml` 的项目根目录。成功后运行 `pwd` 应看到这个路径。

#### 步骤 2：安装锁定 Python 依赖

```bash
uv sync --frozen --extra dev --no-editable
```

命令作用：按 `uv.lock` 安装运行和开发依赖，并安装可运行的项目包。需要 Python 3.11 或以上和 `uv`。`--frozen` 不自行更新依赖锁；`--no-editable` 也适合验证模板资源确实随包安装。

成功后应存在 `.venv/`，下面的入口能打印帮助。若缺少 `uv`，需要先在操作系统安装它；仓库没有捆绑通用系统包管理器。

#### 步骤 3：确认命令、版本及配置路径

```bash
uv run --no-editable anki-pipeline --version
uv run --no-editable anki-pipeline --help
uv run --no-editable anki-pipeline --config config.toml doctor
```

`doctor` 只读检查基础路径存在性与 Python 版本；它不证明所有外部字典、审校侧车、MP3、真题 hash 或 Anki 客户端都有效。某个配置输入不存在时，先更正来源路径，不把空目录当成已准备好。

![实际 CLI --help 运行日志：迁移、词表/PDF、译文、生成、备份恢复与联网补缺命令入口](assets/screenshots/v3.0.0-rc.3/cli-help.jpg)

#### 步骤 4：检查已有新数据库

```bash
uv run --no-editable anki-pipeline --config config.toml check \
  --report output/quality-check.json
```

命令作用：读取新库和音频，写出质量报告；不修改数据库。基础问题导致非零退出。存在需要处理的译文时，普通检查可报告警告；要把未完成的已接受译文也作为失败条件，执行：

```bash
uv run --no-editable anki-pipeline --config config.toml check \
  --report output/quality-check-strict.json --strict-translations
```

成功只能说明该命令覆盖的检查通过，不能替代浏览器、Anki 导入和译文人工审阅。

![实际 check 输出的数据库完整性与计数；警告和未完成翻译仍保留，不声称为零](assets/screenshots/v3.0.0-rc.3/quality-report.jpg)

### 1.10 首次迁移、词表与 PDF 输入

#### 首次迁移：只在目标新库尚未建立时执行

```bash
uv run --no-editable anki-pipeline --config config.toml migrate
```

它只读 V2.0 数据库，核对完整性和来源哈希，保存旧库快照，再建立独立新库，最后复制音频到新版目录。不同的目标库已经存在时会拒绝覆盖。已迁移的本机通常不需要重复执行。

成功后查看 `output/migration-report.json`，核对词卡、原始句子、隔离记录和音频。音频复制若中途失败，新的数据库和部分新音频可能保留；修复输入后再核对，不能为了恢复而删旧音频。

#### 加入新的 Excel 词表

```bash
uv run --no-editable anki-pipeline --config config.toml import-wordbook \
  --file /你的资料目录/词表.xlsx
```

它修改新版库；输入字段为空时保留已有补全资料。写入已有库前有备份。执行后重跑 `check`。

#### 从 PDF 提取新的例句

```bash
uv run --no-editable anki-pipeline --config config.toml extract \
  --pdf /你的资料目录/真题.pdf
```

它只读 PDF，按文字和明确词形提取原句及来源，再写入新版库。新提取句子的中文译文需要后续核验。扫描图 PDF 的文字可提取性取决于输入；本仓库没有自动 OCR 高级识别模型。

**仓库没有 `build-pdf` 或 `export-pdf` CLI 命令。** 此处 PDF 是输入。之前为看修改效果生成的截图 PDF 属于一次性验收材料，不是产品内的试卷 PDF 输出功能。

#### 规则变化后重新分类已有原句

```bash
uv run --no-editable anki-pipeline --config config.toml reclassify
uv run --no-editable anki-pipeline --config config.toml check \
  --report output/after-reclassify.json
```

`reclassify` 重新评估接受 / 隔离状态，保留原文和译文。词典 / Codex 真题构建模式的展示匹配另由相应源规则负责，不能假设旧库重新分类等于重建了全部真题侧车。

### 1.11 按稳定 ID 导出和回填译文

#### 步骤 1：导出待处理 CSV

```bash
uv run --no-editable anki-pipeline --config config.toml export-translations \
  --file output/pending-translations.csv
```

默认只导出待处理行。需要查看全部行时加 `--all`。CSV 包含原句 ID、原文、来源、内容哈希和译文修订信息，不是按当前显示序号随便拼接的表。

#### 步骤 2：人工修改 `translation` 列

不改 `sentence_id`、`word`、`text`、`source`、`content_hash` 和 `translation_revision`。行可以重新排序，但不能复制重复 ID。空白译文不会擦掉已有完成译文。工作 CSV 含学习资料，应保存在本机资料范围内。

#### 步骤 3：整表验证后导入

```bash
uv run --no-editable anki-pipeline --config config.toml import-translations \
  --file output/completed-translations.csv
uv run --no-editable anki-pipeline --config config.toml check \
  --report output/after-translations.json --strict-translations
```

导入先验证完整文件，再事务写入。ID 重复、原文变动、旧表哈希或修订号过期、行属于已隔离例句等情况，会拒绝整次导入，不先写半张表。Codex 题库译文的 JSON 审校管线与这个旧库 CSV 管线是两个入口；不能把 CSV 导入说成已更新 Codex 审校索引。

### 1.12 可选联网补缺

```bash
uv run --no-editable anki-pipeline --config config.toml enrich \
  --provider oxford --limit 10
uv run --no-editable anki-pipeline --config config.toml enrich \
  --provider youdao --limit 10
```

这个维护命令显式请求选定供应商，查询待补的单词；`--limit` 在 1–100 范围内。它按单词记录成功和失败，保留已有内容，不自动后台跑完整词表。网络页面或接口变化会导致明确失败。

网络边界需要区分：`enrich` 是维护者明确执行的联网补词典命令。当前卡片的例句右侧图标是原卷跳转按钮，**没有例句 TTS 功能**；不能把历史模板里的有道朗读代码当成当前功能。完整本地双词典卡包的单词录音从已打包媒体播放，欧路查询则调用本机 `eudic://` 协议。

### 1.13 生成 APKG、网页与离线 ZIP

#### 只生成 APKG 和单卡预览

```bash
uv run --no-editable anki-pipeline --config config.toml build \
  --file "output/27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版.apkg"
```

生成前读取质量结果。失败不发布一个不完整的新包。成功后输出 APKG、`preview.html`、质量及构建报告。这个命令不把卡片自动导入用户正在使用的 Anki 档案。

#### 只更新全卡组网页，不重新打包 APKG

```bash
uv run --no-editable anki-pipeline --config config.toml web-preview
python3 -m http.server 8771 --bind 127.0.0.1 --directory output
```

浏览器打开 `http://localhost:8771/preview-library.html`。第二条命令保持终端运行，按 Ctrl+C 停止。全库 HTML、目录 JSON 和媒体在 `output/web-preview/<input_digest>/`；生成入口成功切换前，旧内容版本保留。

#### 一次生成完整双词典卡包、全库网页和 ZIP

```bash
uv run --no-editable anki-pipeline --config config.toml offline-bundle \
  --file "output/27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版.apkg"
```

当前流程依次读取牛津 / 韦氏、按需 ECDICT 补缺、真题索引及审校侧车、词源，最后生成 APKG、网页和 `output/Anki-完整网页预览.zip`。它是产物全量重建，**不会重写源学习 SQLite、原词典数据库或真题来源数据库**。生成前后核对新库逻辑摘要；输入在构建期间变动会阻止最终发布。

完整资料构建有明确本机前置输入：

- 配置的新库、可用音频、牛津 / 韦氏解包资料与所需解析器。
- ECDICT 与原词源查看器完整资源（启用时）。
- 配套真题仓库结构化卷、Codex 输入 / 译文 / 审校 / 索引及其哈希。
- 阅读题补全与选项组合的已批准 JSON / review，以及相应作者与独立审校证据。

这些资料不因为 Python 单元测试通过就自动存在。纯源码克隆可以安装、看帮助和跑可移植测试，但不能在没有这些外部输入时复现完整 1,960 张内容。应按构建报错补齐可信输入，不能跳过审校检查来强行出包。

#### 独立运行离线 ZIP

解压整个 ZIP，保留相对目录。macOS 可双击包里的 `启动网页预览.command`；其他系统进入解压目录后执行：

```bash
python3 serve_preview.py
```

只启动包内静态服务，使用随机空闲本机端口并打印地址。要只打印、不自动打开浏览器：

```bash
python3 serve_preview.py --no-open
```

包内录音和词典内容独立于原资源目录；跳转原卷仍使用构建时保留的真题地址。

#### 卡组显示名称与稳定身份

当前配置把显示名称和稳定身份分开：

```toml
[deck]
name = "27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版"
identity_name = "考研英语 · 精选真题"
```

`name` 决定 Anki 显示的卡组名；`identity_name` 连同原有 Unit / Lesson 后缀决定数字 deck ID。因此，使用这份配置重建时，可以展示新名称并保留原来 41 个卡组的稳定身份。已交付重命名包也保留了原有笔记、卡片行和媒体。

不要为了改显示名称同时改 `identity_name`。未配置身份名称时，构建器兼容旧规则并使用显示名称作为身份输入；那种配置下改名仍可能改变 deck ID。实际覆盖导入之前，应对那一份旧包与新包重新执行隔离集合核验，不能仅凭稳定 GUID 推断所有导入行为。

### 1.14 备份、恢复、对账与 Anki 验证

#### 新数据库备份

```bash
uv run --no-editable anki-pipeline --config config.toml backup
```

SQLite 在线 backup API 生成带时间戳的独立文件，并运行完整性检查。APKG 和网页 ZIP 保存的是输出，不足以替代包含所有原句、隔离记录和工作译文的新库备份。

#### 恢复到新路径

```bash
uv run --no-editable anki-pipeline --config config.toml restore \
  --file backups/某次备份.sqlite3 --to data/restored-for-review.sqlite3
```

目标必须尚不存在；它不会直接覆盖当前活动库。恢复后需要把一个私人临时配置的 `paths.database` 指向恢复文件，再使用 `--config` 检查和对账。原 `config.toml` 仍指向原活动库时，跑普通 `check` 并不等于检查了恢复文件。

#### 隔离 Anki 集合的覆盖导入核验

本机安装有 Anki 后端时，可先查看核验脚本的真实选项：

```bash
uv run --no-editable python scripts/verify_anki_import.py --help
```

再对明确的旧包和新包执行：

```bash
uv run --no-editable python scripts/verify_anki_import.py \
  --old-package output/此前保留的基线.apkg \
  --package "output/27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版.apkg" \
  --report output/anki-import-verification.json
```

脚本使用一次性临时 collection，检查模型、十字段、GUID、note / card ID、媒体与抽样复习进度。默认 Anki 模块路径是 macOS 已安装客户端的 `app_packages`，其他系统通过 `--anki-packages` 指定；这不表示所有平台都已实测。

证据分三层看：隔离后端核验验证导入身份与媒体；用安装的 Anki reviewer 组件进行离屏渲染验证卡片布局和生命周期；用户真实档案的桌面使用、手机 / 平板、同步属于独立范围。前两者通过，不应声称已替用户导入或同步真实档案。

从旧 V2.0 首次导入重建模型时，稳定 GUID 的新命名空间与旧模板笔记不同；不能承诺自动继承 V2.0 的学习进度。本重建模型之间覆盖更新的结果，以对应新旧包的实际核验为准。

### 1.15 启动真题联动服务与开发命令

#### 启动真题服务

打开另一个终端：

```bash
cd /Users/apple/Documents/PyCharm/Anki/exam-library
python3 scripts/serve_exam_library.py
```

成功后访问 `http://localhost:8765/`。服务仅绑定本机；默认启动会在本地题库缺失或结构化输入更新时重建可再生 SQLite。因此它不是纯“读取一个 HTML 文件”的命令，但不会写入 Anki 新库或真实集合。

端口被占用时可以：

```bash
python3 scripts/serve_exam_library.py --port 8766
```

然后把 Anki 配置 `base_url` 调整为对应地址并重新生成链接。只换服务端口、不换卡片链接，旧卡仍会访问 8765。

#### 真题开发环境和检查

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
.venv/bin/python scripts/verify_library.py
.venv/bin/python scripts/run_portable_tests.py
PYTHONPATH=. .venv/bin/python data/sources/english-exams-reflow-latex/run_portable_tests.py
npm test
```

这些命令位于 **exam-library 仓库**。Python 可移植检查、DOM 测试与原 PDF 严格检查分开。缺少私人来源证据时，严格源重建可能拒绝执行；不能用可移植测试代替逐页题文 / 答案检查。

#### 重建可再生题库

```bash
.venv/bin/python scripts/build_question_database.py
```

它读取结构化 JSON / JSONL、审计和哈希，写临时 SQLite，核对外键及完整性后原子替换 `data/question-bank.sqlite3`。上一个完整版本保存为 `.bak`。数据库不作为网页静态文件暴露，也不保存学习者作答。

完整目录生成器是：

```bash
.venv/bin/python data/sources/exam-library/build.py
```

它可能涉及结构化文件、数据库和目录页的生成；不是只改一个 CSS。源试卷重排 / 公式完整重建另需相应 PDF、答案证据、翻译快照和子目录依赖，部分需 XeLaTeX。维护者只修改 UI 时，无需为了看截图重新转录全部原稿。

### 1.16 Anki 源码测试和验证如何逐步执行

返回 Anki 仓库，运行：

```bash
cd /Users/apple/Documents/PyCharm/Anki/anki_rebuild
uv run --no-editable python -m unittest discover -s tests -v
uv run --no-editable python scripts/verify_project.py

# Node.js：^20.19.0、^22.13.0 或 >=24；CI 使用 24
npm ci
npm run check
npm test
```

第一条验证纯函数、存储、路径、打包、来源和异常回归；第二条核对源码语法、版本文件一致性、模板分离、项目记录与已有素材。JS 的语法和 Node 交互检查按本仓库锁定的测试环境执行；不能依赖旁边真题仓库碰巧装好了 jsdom 才算独立源码可测。

一次完整验收至少分开回答：

1. **数据和计数**：词卡不丢失，来源不改写，裸词选项 / 补全副本不会制造词频，缺失译文不混入输出。
2. **安全生成**：路径不越界、字段转义、媒体内容正确、过期审校拒绝、构建失败保留旧入口。
3. **可运行内容**：全目录、搜索、翻面、发音和词源展开都可使用，不只是命令退出码为 0。
4. **联动**：实际点击多个原句，在两种阅读器核查题目位置与外框；双向补全题干和选项都框，普通链接行为不被扩大。
5. **客户端范围**：隔离 Anki 导入、原生 reviewer 布局与真实用户配置使用分别记录；没有运行的范围写清楚。

### 1.17 功能截图的覆盖与证据方式

截图必须能看到功能内容，并且与实际操作联系起来。跳转、显示答案、词源展开、图片切换和双语对应至少保留前后状态；不能只有结果页，也不能只展示一个恰好可用的单词就泛化到所有词卡。

下面是 rc.3 历史功能截图文件键。这批图片保存在 `assets/screenshots/v3.0.0-rc.3/`；捕获清单应记录文件名、功能、界面入口、捕获方式与适用范围。一个截图可以证明同屏上多个控件的位置，但声音播放、哈希校验或事务回滚仍需要对应运行结果。

| 截图键 | 必须看得到的功能 / 证据 |
|---|---|
| `card-front`、`card-back-overview` | 正反面同位置的发音选择器、Word / IPA、查词、播放圆圈。 |
| `card-pronunciation` | 来源选择与实际录音 / 回退状态。 |
| `card-forms`、`card-ecdict-fallback` | 完整释义、词形、派生词、标签和 ECDICT 缺口来源。 |
| `card-etymology-collapsed`、`card-etymology` | 原词源树、同根词、例句以及展开前后。 |
| `card-examples`、`jump-option-before` | 完整例句、译文、目标词、恢复题干、候选身份与来源路径。 |
| `card-cloze-completion`、`jump-twoway-before`、`card-sentence-insertion` | 三类回填与下划线。 |
| `card-examples`、`card-chunk-english`、`card-chunk-chinese` | 无荧光 / 英文触发 / 中文触发的双语状态。 |
| `jump-option-before`、`jump-passage-after`、`jump-option-after` | 实际点击前及两种原卷定位结果。 |
| `jump-twoway-before`、`jump-twoway-after` | 同一双向补全从卡片到原题，题干和正确选项同时框出。 |
| `card-back-overview` | 原位置次数、覆盖分母和半星显示。 |
| `card-back-overview`、`card-content-end-countdown` | 顶部没有占位悬浮栏，倒计时位于翻译末尾。 |
| `card-front`、`card-deck-search`、`card-empty-search` | 完整目录、筛选 / 搜索、无结果状态。 |
| `card-mobile-directory`、`historical-local-dictionary-portable-humour` | 窄屏目录，以及 ZIP 独立运行入口。 |
| `exam-catalog`、`exam-parallel`、`exam-reflow`、`exam-parallel` | 真题总目录及三个阅读模式。 |
| `exam-reading-settings`、`exam-reviewed-translation` | 目录、设置、专注 / 进度、工具栏译文与双语内容。 |
| `exam-cloze-before`、`exam-cloze-answer`、`exam-immersive` | 选项作答、答案展开前后、沉浸阅读。 |
| `exam-cloze-before`、`exam-short-headings`、`exam-ordering` | 四选项、两列标题库、排序五字母与答案右上角。 |
| `exam-redraw-first-load`、`exam-redraw-original`、`exam-redraw-return` | 首次进入、查看原图、返回重绘的连续状态与同一尺寸。 |
| `exam-image-audit`、`exam-crop-audit` | 重绘审阅与原页裁切边界审阅。 |
| `exam-structured` | 结构化卷 / 题的实际只读接口结果。 |
| `cli-help`、`quality-report` | 全部维护命令入口与真实质量报告；不伪造后台功能的可视化面板。 |

#### rc.3 历史补充截图与证据目录

这批历史截图来自当时的实际 UI 操作，元信息与 SHA-256 见 [capture-manifest.json](assets/screenshots/v3.0.0-rc.3/capture-manifest.json)。390×844 是浏览器手机比例，不宣称真机 AnkiMobile 验收；原段落跳转图为 319×702 窄屏，两个选项跳转组为桌面比例。命令截图是已执行日志的查看页，不是新管理面板。此前图片按 `historical-` 前缀归档并标注。

![按年份筛选后实际资料和版本按钮](assets/screenshots/v3.0.0-rc.3/exam-filter.jpg)

![专注阅读隐藏工具区](assets/screenshots/v3.0.0-rc.3/exam-focus.jpg)

![整卷原序作答、章节目录与沉浸模式入口](assets/screenshots/v3.0.0-rc.3/exam-full-paper.jpg)

![例句跳转版本可选择整卷版或LaTeX重排](assets/screenshots/v3.0.0-rc.3/card-reader-selector.jpg)

![点击前：正文原句有中文对应与详细来源](assets/screenshots/v3.0.0-rc.3/jump-passage-before.jpg)

![390×844 手机版正面：目录折叠、发音来源在卡片外、圆形播放图标](assets/screenshots/v3.0.0-rc.3/card-mobile.jpg)

![390×844 手机版背面：释义、词频和可继续滚动的例句](assets/screenshots/v3.0.0-rc.3/card-mobile-back.jpg)


## 2. 技术栈

### 2.1 语言、库、运行时与工具

| 分类 | 技术 | 证据文件 | 在项目里的作用 | 小白解释 |
|---|---|---|---|---|
| 主要语言 | Python ≥ 3.11 | `pyproject.toml` | CLI、资料读取、校验、SQLite、生成 | 把文件和资料变成可复习产物的主程序。 |
| 浏览器语言 | 原生 JavaScript | `templates/script.js`、`card-chunks.js`、`countdown.js`、`library-preview.js` | 卡片生命周期、发音、双语对应、倒计时及全库浏览 | 负责用户点击后发生什么。 |
| 页面与样式 | HTML / CSS | `templates/front.html`、`back.html`、`style.css` 等 | 正反面模板、响应式排版 | HTML 定义内容，CSS 定义颜色、布局和尺寸。 |
| 包管理 | uv 与锁文件 | `uv.lock`、开发 / CI 命令 | 锁定 Python 依赖 | 让不同环境安装同一套依赖版本。 |
| Python 构建 | setuptools 80.9.0 | `pyproject.toml` | 构建 wheel，附带模板资源 | 把代码与资源打成可安装包。 |
| Anki 打包 | genanki 0.13.1 | `pyproject.toml`、`packaging.py` | 生成模型、笔记、牌组与 APKG | 按 Anki 可识别的格式输出学习卡。 |
| Excel | openpyxl 3.1.5 | `inputs.py`、依赖声明 | 读取词表 | 把 `.xlsx` 中的单词和课程信息读出来。 |
| HTTP | requests 2.33.0 | `inputs.py` | 显式词典请求及受限音频下载 | 仅在维护者启动相关命令时访问外部服务。 |
| HTML 解析 | lxml 6.1.0、标准库 HTMLParser | `inputs.py`、`text.py`、`etymology.py` | 解析来源内容、提取纯文本、保留已审 HTML | 区分正文、结构和可执行内容。 |
| PDF | PyMuPDF 1.26.3 | `pdf.py`、依赖声明 | 读取 PDF 文本与页面信息 | 不自动等于 OCR，也不自动输出新的 PDF。 |
| 配置 | TOML / tomllib / dataclass | `config.py`、`config.toml` | 解析路径、来源和限制 | 明确告诉程序读哪里、写哪里。 |
| 存储 | SQLite / sqlite3 | `store.py` | 新学习库、事务、在线备份 | 本机单文件关系数据库，不需要远端数据库服务。 |
| 可移植数据 | JSON / JSONL / CSV | `translations.py`、`codex_exam_index.py` | 原句、译文、审校、清单、导入导出 | 可读的结构化文件，不靠显示顺序猜对应。 |
| 身份与完整性 | SHA-256、稳定 Anki GUID | `text.py`、`store.py`、`packaging.py` | 绑定内容、源文件和身份 | 检查是不是同一份内容，不评判译文语义。 |
| 静态网页服务 | Python http.server | 使用命令、`web_bundle.py` | 本机网页预览 | 托管已生成文件，不是 Anki 评分服务器。 |
| 本机 Anki 核验 | 已安装 Anki 后端与 reviewer / Qt WebEngine | `scripts/verify_anki_import.py`、本地验收记录 | 一次性 collection 导入与实际组件渲染 | 与直接修改用户正在使用的档案是不同操作。 |
| Python 测试 | unittest | `tests/test_*.py` | 逻辑、异常、存储、打包回归 | 不依赖某一次人工点开页面来找基础错误。 |
| Schema 检查 | jsonschema 4.25.1 | dev 依赖、`scripts/verify_project.py` | 项目治理记录结构 | 并非所有学习 JSON 都用这一个库验证；不少是明确手写校验。 |
| JS 测试 | Node `node:test`、jsdom 29.1.1 | `tests/*.cjs`、本仓库 `package.json` / `package-lock.json` | DOM 与事件回归 | 模拟页面结构；不替代 Safari / Anki 的真实显示。 |
| CI | GitHub Actions | `.github/workflows/checks.yml` | Python 版本矩阵、源码及模板测试、wheel 安装检查 | PR 上自动执行可移植检查。 |
| 版本控制 | Git / 公开 GitHub 仓库 | 远端、PR、CHANGELOG | 审查源码与功能文档 | 本地 APKG 与原始资料不默认推入 Git。 |
| 文档绘图 | Mermaid | 本文第 4 章 | 流程、关系、时序和边界 | 通过文本描述图，而不是截图里的装饰线。 |

本项目没有 React / Vue 框架、SPA 路由器、Redux、ORM、应用用户认证、消息队列或自动后台任务。对应功能使用原生模板、URL 参数、页面 DOM 状态、`localStorage` 和显式 CLI。源码没有证据支持把它描述成云端平台或微服务系统。

### 2.2 真题仓库的技术补充

| 分类 | 配套技术 | 证据 | 作用 |
|---|---|---|---|
| 本地 HTTP 服务 | 标准库 ThreadingHTTPServer | `exam-library/scripts/serve_exam_library.py` | 同站点提供静态页和只读 API。 |
| HTML 清洗 / 结构读取 | BeautifulSoup 4.15.0，lxml | 配套 `requirements.txt`、生成器 | 从来源 HTML 建立题目及语义结构。 |
| 读取数据库 | SQLite | `question_bank_schema.sql`、`question_database_api.py` | 可再生题文、选项、答案和来源块。 |
| SVG / 重排 | 原稿 SVG、LaTeX 来源、HTML 重排 | `data/sources/*`、共享 reader | 保留原卷，同时适应窗口阅读。 |
| 公式 | 对应子目录本地公式渲染资源和构建工具 | 数学 / 408 / 政治子目录与共享资源 | 具体完整源重建依赖按子目录说明安装，不是 Anki 包自动装齐。 |
| 前端测试 | jsdom 29.1.1、Node | 配套 `package.json` / lock | 总目录、阅读、译文、答案与图像控制的 DOM 回归。 |
| API 状态 | 固定选项 ID、答案三态、种子乱序 | `question_database_api.py` | 防止展示顺序变化导致错误判分。 |

Anki 项目对配套输入主要是读取文件；运行时跳转使用普通浏览器 URL。没有两个仓库共用一个可写数据库，没有把 Anki scheduler 搬到真题服务。

### 2.3 工程风格和具体证据

| 工程做法 | 具体体现 | 为什么采用 |
|---|---|---|
| 模块化本地流水线 | CLI 调用 migration / store / lexical / exam / packaging 各模块 | 让输入、判断和输出边界清楚，便于单独测试。 |
| 纯函数优先 | `text.py`、`forms.py`、`exam_frequency.py`、范围校验 | 同样输入得到同样结果，计数和匹配不会暗中改数据库。 |
| 类型与不可变数据 | `Config`、`_Alignment`、索引文件 Snapshot 的 dataclass / 注解 | 限制模块传递数据的形状；不是依赖隐式全局变量。 |
| 事务写入 | `BEGIN IMMEDIATE`、异常 rollback | 一份错误译文表不能造成半数行已更新。 |
| 读写分离 | `mode=ro`、`query_only=ON`、项目根路径保护 | 构建只读输入，资料写入只进入明确的新库或输出。 |
| 发布产物前校验 | 临时文件、清单验证、`os.replace` | 当前可用产物不被失败的半成品替换。 |
| 来源可追溯 | 原始行 JSON、原句 ID、源块、hash、review、来源路径 | 看见一个卡片组合时仍能找到原卷的两部分。 |
| 显式失败 | ValueError / 带范围的异常、CLI 非零状态、结构与 hash 检查 | 缺译文、过期审校或来源歧义不被静默当成功。 |
| 保留原显示语义 | 十个 Anki 字段、FrontSide、eudic 协议、原词源 DOM | 更新资料和布局时减少学习操作变化。 |
| 交互脚本分离 | 发音、chunk、词源和 countdown 分文件 | 防止一种交互修改带坏其他交互。 |
| WebView 生命周期意识 | 委托事件、单次绑定、切卡清状态、Mutation / ResizeObserver | Anki 会复用页面容器，不能假设每张卡都会刷新整个浏览器。 |
| 分层证据 | Python / DOM / browser / backend / semantic review | 每种验证只证明自己观察到的范围。 |

### 2.4 状态、缓存、路由、网络和部署边界

- **路由**：CLI 是子命令；网页是实际 `.htm` / `.html` 地址与 query 参数；全库预览保留卡组和卡片地址状态，没有额外路由框架。
- **页面状态**：当前卡、翻面、选项、chunk 固定与展开状态由页面脚本管理。发音 / 阅读偏好和最近阅读可由本机 `localStorage` 保存。
- **缓存**：网页素材使用内容摘要目录；练习页面对答案请求有内存缓存。不存在 Redis 等统一远端缓存。
- **后台执行**：没有自动调度 enrich、自动翻译、轮询云数据库或消息队列；用户显式运行 CLI。
- **账户与认证**：本地工具依靠操作系统文件权限，公开源码可直接浏览，仓库写权限由 GitHub 管理；没有自己的注册、登录或多租户权限系统。
- **网络**：词卡本地资料与本地录音可离线；欧路协议是本机 app 调用；原卷跳转去配置的真题地址；`enrich` 是维护者主动执行的联网补词典入口。当前例句图标执行原卷跳转，不提供 TTS。
- **部署**：本机 Anki、静态预览服务、真题本地服务是三个独立运行面。仓库未提供云部署、Docker / Kubernetes 清单或公网鉴权方案。

### 2.5 源码许可与第三方内容的边界

**主分支保护与维护者同意：** `main` 必须经过 PR，并通过最新基础分支上的 Python 3.11 / 3.13 两项 CI；管理员也受规则约束，禁止强推和删除，审查讨论必须解决。Codex 在合并每个 PR 前必须在对话中取得维护者针对该 PR 的明确同意；CI 或子代理审查不代替本人同意。GitHub 不核实对话审批，必需的独立账号 Approve 数为 0。执行规则见根 [AGENTS.md](AGENTS.md)，实际配置、证据及边界见 [分支保护说明](docs/BRANCH_PROTECTION.md)。

**MIT 已通过 GitHub 平台识别。** 仓库已公开，[PR #3](https://github.com/CHNragdoll/anki-pipeline/pull/3) 已合并到 `main`，GitHub [许可证接口](https://api.github.com/repos/CHNragdoll/anki-pipeline/license) 实测返回 `key: mit`、`spdx_id: MIT`，主页显示 **MIT license**。根 `LICENSE` 的授权正文与 [GitHub MIT 标准全文](https://api.github.com/licenses/mit) 一致；远端许可证、干净 wheel 和仓库外安装后的许可证均与根文件逐字节一致，包元数据声明 `License-Expression: MIT`。完整结果见 [本轮验证](docs/rc3-verification.json)。

![GitHub 公开主页：main 分支已显示 MIT license，PR #3 已合并](assets/screenshots/v3.0.0-rc.3/github-mit-public.jpg)

**本项目原创源码和本项目原创文档采用 [MIT License](LICENSE)。** 使用、修改或分发这些原创软件部分时应保留 MIT 的许可和版权声明。

MIT 声明不会重新授予第三方词典、历年真题、音频、词源图片、原查看器内容或上游依赖的权利。相关资源仍适用各自来源许可和使用条件；ECDICT 的 MIT 声明随相关离线内容保留。PyMuPDF 的 AGPL / 商业许可也没有因本仓库采用 MIT 而消失，具体依赖与许可记录见 `docs/DEPENDENCIES.md`。

可移植源码、截图说明与本地含学习资料的 APKG 是不同分发对象。目前三套 APKG 分别位于首页列出的独立 Release；红宝书还提供交付报告、核验 JSON 与摘要文件，文档和截图保存在仓库中。需要对外分发第三方资源或提供服务时，应逐项核对来源许可，不能只展示本仓库 MIT 就宣称整包全部第三方素材可自由再分发。

## 3. 算法及数学模型

### 3.1 不存在的模型先说明

仓库里没找到独立实现的艾宾浩斯遗忘曲线调度、机器学习推荐、神经翻译模型、向量检索、OCR 训练或自研 FSRS。卡包名称不是实现证据。Anki 客户端依据自己的牌组 / 调度设置安排复习；本项目不根据词频星级自动调整复习间隔。

本机独立网页复习使用已有 FSRS 库，不是本仓库自研调度器，也不是 CLI 静态预览的一部分。核心逻辑是精确匹配、来源绑定、答案补全、计数、范围映射及可恢复的数据流程。下面逐项说明实际可见的规则。

### 3.2 明确词形与完整 token 匹配

**位置：** `text.py`、`forms.py`、`match_forms.py`、`exam_library.py`。

**解决问题：** 防止 `rate` 命中 `rather`、`theme` 命中 `them`，以及把一个词的派生词或父词变化误计入该词。

**输入：** 词卡单词、明确美式拼写、韦氏或 ECDICT 屈折形式、原英文文本。

**输出：** 真实目标词的半开区间 `[start, end)`；同一规则用于筛选、目标词标记与原位置词频。

**步骤：**

1. 对词头做明确的 Unicode / 大小写规范处理；原英文正文不为方便而任意重写。
2. 选择本卡的明确词形来源。当前本地词典 / Codex 模式使用 `infer=False`，不把通用自动后缀猜测加入匹配。
3. 只接受复数、第三人称单数、现在分词、过去式、过去分词、比较级、最高级等明确屈折种类。
4. 词形记录有 `base` 时，必须属于本卡原词或明确标题拼写。父词变化、派生词和 ECDICT 0 / 1 词元关系不作为别名。
5. 使用转义后的候选集合和完整词边界查找：

```text
(?<!\w)(?:form_1|form_2|...)(?!\w)
```

6. 记录所有实际出现范围，不只记录第一处。再应用按原位置核准的同形异义排除。

**小白解释：** 先列出确实属于这个词的拼写，再在句子中找完整词；不是只看几位字母相同。

**复杂度：** 当前实现按词卡扫描句子。用 `C` 表示词卡数、`T` 表示语料总字符、`V` 表示候选词形数，可把直接扫描工作量保守理解为与 `C × T × V` 相关；实际耗时受正则引擎和候选长度影响，仓库没有给出严谨的跨环境性能模型。

**边界：** 老数据库迁移 / PDF 通用入口还保留保守形态函数；不能把它与当前 Codex 模式的 `infer=False` 混为同一配置。没有可信词形不靠模糊命中“增加覆盖”。

### 3.3 原句身份、文件哈希与审校绑定

**位置：** `store.py`、`text.py`、`codex_exam_index.py`、`reading_completion.py`、`option_translation.py`。

**解决问题：** CSV 换行、例句重新排序、试卷重排或译文更新后，仍知道文字属于哪个原句；过期审校不能套到新文本。

**主要规则：**

```text
card_id = SHA256(JSON(sheet, lesson, word))
legacy_sentence_key = SHA256(JSON(normalized_word, normalized_sentence, normalized_source))
file_hash = SHA256(exact_file_bytes)
english_hash = SHA256(exact_English_UTF8)
translation_hash = SHA256(exact_Chinese_UTF8)
```

卡片身份由课程与词头派生，旧句子内容身份不依赖 `[n]` 显示序号。Codex 真题句子另有带 paper / paragraph / sentence 的稳定索引 ID，并绑定原文字、来源块、片段位置、译文和审校 hash。

校验链是：输入清单 → 每卷原输入 → 译文文件 → 批准审校 → 索引 → 原结构化题目 / 答案 → 补全侧车与独立审校。JSON 重复字段、未知 schema、范围越界、缺行、未批准或来源变化均应拒绝。

**复杂度：** hash 是按字节顺序扫描，时间 `O(B)`、流式文件 hash 的额外空间 `O(1)`；解析 JSON 本身需要与输入规模相关的内存。

**边界：** hash 相同证明拿的是同一份内容，不能证明来源绝对正确或中文表达准确。语义准确性仍依靠原稿核验和独立审校。

### 3.4 来源规范去重和同形异义排除

**位置：** `exam_library.py::_canonical_codex_sentences`、`occurrence_exclusions.py`。

**解决问题：** 同一个印刷选项可能既出现在段落材料中又被结构化导出为答案选项；若按两条记录各算一次，会虚增词频。

程序尽量根据明确的 paper、原 block / option、原 hash 与范围建立 `canonical_occurrence_key`。文本相同但原位置不同的两句仍是两个来源，不能按英文字符串直接去重。导出重复的同一位置则合并为一个来源，保留别名和重复上下文。

同形异义排除使用已声明的句子 ID、词卡 ID 和 `[start,end)`；不是把所有相同拼写全局删除。排除文件 hash 也被核对，每项必须确实匹配到当前词形与位置；不能悄悄留下失效的排除记录。

**复杂度：** `S` 个索引记录的 key 归并通常用字典，期望 `O(S)` 时间与 `O(S)` 空间；生成顺序或分组仍有相应排序成本。

### 3.5 正确答案补全、候选选项上下文与坐标映射

**位置：** `reading_completion.py`、`option_context.py`、`sentence_insertion.py`、`option_translation.py`。

**输入：** 明确题目关联、原题干、原选项、可信答案 token、原译文及已审组合译文。

**输出：** 卡片完整英文、完整中文、插入答案范围、原题与选项各自来源引用和 hash。

有唯一填空时：

```text
display = original_before_blank + inserted_option + original_after_blank
insertedRange = [插入起点, 插入终点)
```

插入前后按文字边界补必要空格，避免多一个重复句点；英文实际答案范围加下划线。原题干范围与选项范围通过明确偏移映射到展示字符串，而不是用“第几个单词”猜坐标。

没有空位的候选题，问题和选项保留分段关系。Part B 句子插入可能由多个已审原选项句组成，要求原范围覆盖、译文引用和明确答案一致。

**复杂度：** 单条组合文本拼接和范围验证与文本长度线性相关；题目 / 选项查找通过预先索引，整个集合另有来源读取和分组成本。

**边界：** 多空、关联歧义、答案缺失、未找到唯一选项、译文未审或残留空位不能自动通过。错误候选项的完整译文只是该候选表达的意思，不改变正确性。

### 3.6 双向补全：显示合并与原位置计数分别算

**位置：** `exam_library.py`，`retained_completions` 与 `deduplicated_option_contexts`。

两条生成路径可能得到同一个结果：

```text
路径一：题干命中 w → 题干 + 正确选项 A
路径二：选项 A 命中 w → 原选项补回题干 → 同一个题干 + A
```

只有同题、当前候选确实为正确项、完整英文相同并通过来源绑定，才合并成 **1 条展示例句**。合并项仍保存题干和正确选项的来源；跳转额外携带 `anki-codex-context`，让两个部分都加框。

**计数公式：**

```text
展示例句数 = 最终保留的派生例句条数
词频 = 各不同原始印刷位置的有效出现次数之和
```

下面回答具体容易混淆的情况。假设同一道题的题干和每个命中选项都只有一次 `w`，A 是正确答案：

| 原卷情况 | 卡片可显示的组合 | 展示条数 | 原卷词频 |
|---|---|---:|---:|
| 只有题干有 `w` | 题干 + A | 1 | 1 |
| 只有 A 有 `w` | 题干 + A | 1 | 1 |
| 题干与 A 都有 `w` | 两条生成路径合并为题干 + A | 1 | 2 |
| 题干、B、C、D 有 `w`，A 没有 | 题干 + A，以及 B / C / D 各补回题干 | 4 | 4 |
| 题干、A、B、C、D 都有 `w` | 题干 + A 合并；B / C / D 各保留候选组合 | 4 | 5 |
| 一个原句中 `w` 出现两次 | 该来源的一条显示例句 | 1 | 2 |
| 某裸词选项有 `w` | 可以没有可显示完整例句 | 0 | 该选项的实际次数 |

表中按有效非裸词候选与已有译文 / 来源条件举例。复制进 B / C / D 的题干可以在显示里重复出现 `w`，但它还是原卷的同一个位置，不能再数三次。题干补 A 后，A 的出现也不再作为“插入了一个新词”额外计数。

### 3.7 词频、来源句数、试卷覆盖和半星模型

**位置：** `exam_frequency.py`。

**输入：** `(paper_id, original_sentence_identity, sentence_index, occurrences)` 的记录，以及语料试卷数。

**步骤：**

1. 按不同来源身份去重。同一身份重复提交必须带相同计数，否则报错。
2. 只保留次数大于 0 的命中来源。
3. 求次数之和、不同命中句子数、不同命中试卷数。
4. 核对数量关系，避免计数超出语料。
5. 通过固定阈值给出 0–5 的半星。

```text
F = sum(每个不同原来源位置的有效次数)
S = 命中来源句身份的数量
P = 命中试卷集合的大小
N = 本次有效语料试卷数

0 <= P <= S <= F
P <= N
coverage_display = P / N 套
stars = count(threshold <= F) / 2
thresholds = [1, 2, 3, 5, 8, 13, 20, 30, 50, 80]
```

“覆盖 9 / 44 套”是数量比，UI 并不把它与出现次数混成百分比评分。

| 出现次数 F | 星级 |
|---:|---:|
| 0 | 0 |
| 1 | 0.5 |
| 2 | 1 |
| 3–4 | 1.5 |
| 5–7 | 2 |
| 8–12 | 2.5 |
| 13–19 | 3 |
| 20–29 | 3.5 |
| 30–49 | 4 |
| 50–79 | 4.5 |
| ≥ 80 | 5 |

`ambition` 的 27 次因此是 3.5 星。这是明确的业务分段规则，不是难度预测、考试概率、遗忘率或经过统计训练的模型。

**复杂度：** `M` 条来源计数用字典归并，期望 `O(M)` 时间和 `O(M)` 空间；星级 `bisect_right` 对 10 个固定阈值二分，成本可视为常数。

**边界：** 全卡 `total_occurrences` 是每张卡的 F 合计；不同词卡若共享明确词形，不能把该合计当成语料里互不重叠的 token 总数。显示例句可因为裸词不展示、组合去重、原句多次出现等原因与 S / F 不同。

### 3.8 双语对齐、重叠范围和荧光交互

**位置：** `translation_alignment.py`、`packaging.py`、`templates/card-chunks.js` / `.css`。

范围统一采用**原字符串的 Unicode codepoint 半开区间**：

```text
0 <= start < end <= len(exact_text)
span_text = exact_text[start:end]
```

它不是 UTF-16 code unit，不是 HTML 转义后字符串的下标，也不是删除标点后的词序。渲染前先核对英文和中文 hash；HTML 转义只能发生在已验证范围分段之后。

程序验证 `equivalent` / `implicit` / `untranslated`：明确对等关系必须有中文范围；隐含或未译关系没有中文范围并需要解释。精细对齐选择时，精确英文范围优先，其次选唯一最短的包含片段；不能拿整句对齐来假装每个词都能对应。

重叠 / 相邻中文范围合并显示，保留多对一 / 一对多的 chunk ID。交互时英文重叠使用已有首 ID 优先，中文可以触发多个已确认英文 chunk 的并集；选择范围仅作用于当前 `.example-card`。

```text
active_chunks = 当前例句里与所选有效 chunk IDs 有交集的片段
active_background = #ffe69b
```

**复杂度：** 范围排序与合并约 `O(K log K)`；单次激活遍历当前例句的 chunk 节点，约 `O(K)`。这不是从全部中文里做语义检索。

**边界：** 对齐验证证明结构可安全使用，不证明语言对应一定正确。有些组合没有现成索引，保持普通文字；个别已存在的语义对应仍可能需人工修正。

### 3.9 来源层级与导航参数

**位置：** `source_paths.py`、`exam_library.py`；配套仓库 `ui/codex-sentence-link.js` 等定位脚本。

来源从原卷 title、真实目录父链、原 block、question 与 option 的绑定生成。题目层级覆盖普通句子层级时也必须有结构化来源证据。最终用 `" ➫ "` 拼接，不回退为暴露内部 ID 的伪路径。

跳转参数分开存储：

- `anki-codex-sentence`：原句身份。
- `anki-codex-hash`：准确原英文 hash。
- `anki-codex-review`：相应审校内容 hash。
- `anki-codex-en`：原英文位置范围，不是组合后的展示位置。
- `anki-codex-context`：仅合并双向补全时增加题干、选项各自的已审引用。

阅读器先核对身份和 hash，再定位实际 DOM / SVG。选项页面滚动到所属题干处，框定位内容；框和临时双语荧光属于不同反馈。后者按 hover / click 取消，不把卡片目标词永久标黄。

**边界：** 跨页 / 跨块需要多个原引用，不能用一份组合后的 hash 替代全部原片段。URL 参数不是权限凭证，也不是远程 API 签名。

### 3.10 稳定 Anki 身份、自然排序和媒体验证

**位置：** `packaging.py`、`pipeline.py`、`web_preview.py`。

数字模型 / 牌组 ID 的实际规则是：

```text
id = first_8_bytes(SHA256("anki-rebuild/namespace/name"))
     mod 2,147,483,646 + 1
note_guid = genanki.guid_for("anki-rebuild-card-v1", card_id)
```

这里数字 deck ID 的 `name` 是稳定身份名称 `deck_identity_name` 加上原有 Unit / Lesson 路径；用户看到的显示名称由 `deck_name` 单独提供。项目配置固定旧身份名称，展示新卡组名称。未设置 `deck_identity_name` 时，构建器才回退到使用显示名称派生身份。

模型保留 `考研英语词汇 v1`，十字段顺序是：

```text
Word, Phonetic, Definition, SimpleDefinition, Level,
WordForms, Audio, Examples, Meta, Note
```

Unit / Lesson 按自然数字排序，避免 Lesson 10 排在 Lesson 2 前。HTML 字段先转义，媒体名称、路径和 MP3 内容受校验，不能把不安全文件名直接抽取到任意目录。

**复杂度：** `C` 张卡的排序约 `O(C log C)`；媒体完整 hash 与总媒体字节数线性相关。不同环境导入能否维持真实 note / card ID，要用那一份旧包和新包实际核验，不仅看 GUID 公式。

**边界：** 保留 `identity_name` 和 Unit / Lesson 路径时，修改显示名称不会改变数字 deck ID；改变身份名称、课程路径或卡片 ID 则可能产生新身份。包级核验仍需检查那一份实际产物，尤其是跨旧版导入时。

### 3.11 可恢复的事务、备份与原子发布

**位置：** `store.py`、`migration.py`、`translations.py`、`cli.py`、`packaging.py`、`web_preview.py`、`web_bundle.py`。

数据库写入先检查、备份，再以 `BEGIN IMMEDIATE` 写入，成功 commit，异常 rollback。旧源数据使用只读连接，源文件前后 hash 不应变化。restore 写新的目标，再核对完整性，不覆盖活动库。

产物发布按以下流程：

```text
读取可信输入 → 生成临时输出 → 校验文件和清单
→ 再次确认输入没变化 → os.replace(临时输出, 公开入口)
```

全库网页内容目录由输入摘要命名；旧目录保留，入口只指向完整版本。离线 ZIP 校验成员和 CRC，APKG 及媒体也在发布前核对。

**边界：** 单个 APKG / HTML / ZIP 的原子替换不是跨三个文件的分布式事务；整套产物的一致性应看最终交付报告，不能拿生成过程中出现的一个新文件代表整套成功。

### 3.12 配套题库：答案三态、固定选项和可重现乱序

**位置：** `exam-library/scripts/build_question_database.py`、`question_database_api.py`。

选项正确性采用三态：

```text
is_correct = 1     有明确来源，并确定是正确项
is_correct = 0     有明确来源，并确定不是正确项
is_correct = NULL  未核实、缺失或歧义
```

只有 `explicit` 答案、能够解析为存在的选项、且与题型匹配，才允许自动判分；重复原标记、答案不匹配、只有说明没有选项答案等情况保留原材料，但不制造布尔正确性。

读取时的种子乱序实际是：

```python
random.Random(f"{seed}:{question_id}").shuffle(options)
```

随机数生成器只决定显示顺序。答案关联固定 `option_id`，不是临时显示的 A / B / C / D；同一 seed 与同一输入顺序可以重现。它不是密码学随机，也没有参与 Anki 学习调度。

**复杂度：** 每题 `O(K)` 的 shuffle；整卷按题和选项数量读取。API 题文与答案分端点，避免普通题文请求提前暴露正确选项。

### 3.13 题库可再生存储与输入一致性

**位置：** 配套 `build_question_database.py`、`question_bank_schema.sql`、`serve_exam_library.py`。

结构化 JSON / JSONL、审计记录和输入 hash 是建库输入；SQLite 的 `input_hashes` 记录来源。新库先在同目录临时文件生成，验证外键、数量和完整性，保留上一次 `.bak` 后替换。语义层额外保存来源块 / JSON path、共享上下文和延续关系；不会把一个同页答案错误归给另一题。

服务通过输入更新时间、数据库模式和语义模式判断是否需重新建库。数据库构建失败时读取 API 应报错，而不是把未知数据自动补成答案。

### 3.14 倒计时的时间数学与生命周期

**位置：** `templates/countdown.js`。

```text
r = max(0, ceil((target_timestamp - Date.now()) / 1000))
days = floor(r / 86400)
hours = floor((r mod 86400) / 3600)
minutes = floor((r mod 3600) / 60)
seconds = r mod 60
```

目标时间带 `+08:00`，所以不会把 UTC 当作北京时间。每秒刷新，时间到后停止旧定时器并显示开始状态。翻面或切卡时检查当前包装 / footer 是否仍属于当前节点，清理旧状态；脚本重复执行不再创建多条倒计时。

**复杂度：** 每次刷新 `O(1)`；布局观察器刷新涉及当前卡的实际节点。它不连接日历服务器，也不计算遗忘率。

### 3.15 原图 / 重绘图加载状态

**位置：** 配套 reader 与 `practice/full-paper.js`、重绘映射及对应测试。

```text
初始可读原图 → 请求重绘图 → 重绘加载成功且尺寸有效 → 显示重绘
                         ↘ 失败 → 保留原图
```

用户切换原图时只是改变当前显示状态，不改变图片映射或来源。首屏需要主动加载待显示重绘；不能用隐藏节点的懒加载制造循环等待。图像尺寸使用一致的显示约束，SVG 顺序图与写作图片分别配置，避免一张图撑满整页。

## 4. Mermaid 图

这些图对应实际模块、文件、数据或交互。ER 图表示数据库真实关系；跨仓库来源图表示应用层引用，不能误当作两个 SQLite 之间存在外键。

### 4.1 总流程图：从原资料到学习

```mermaid
flowchart TD
  Legacy["旧词库 / Excel / 音频，只读"] --> Migration["migrate / import-wordbook"]
  PDF["本地 PDF，只读"] --> Extract["extract 原句"]
  Migration --> Study[("新版 data/anki.sqlite3")]
  Extract --> Study
  Study --> CSV["导出译文 CSV"]
  CSV --> Human["人工修订并核对来源"]
  Human --> Import["整表验证 + 事务导入"]
  Import --> Study
  Study --> Check["quality 检查"]
  Dictionaries["牛津 / 韦氏 / ECDICT，只读"] --> Build["组合构建输入"]
  Etymology["原词源与查看器，只读"] --> Build
  Exams["真题结构 / 已审句子索引 / 补全侧车"] --> Build
  Check --> Build
  Build --> Package["APKG + 模板 + 本地媒体"]
  Build --> Web["全卡组网页 + 共享媒体"]
  Web --> ZIP["完整离线 ZIP"]
  Package --> Anki["Anki 导入与客户端复习"]
  Web --> Browser["网页搜索 / 翻面 / 双语对应"]
  Anki --> Jump["点击原句链接"]
  Browser --> Jump
  Jump --> Reader["8765 原卷 / 整卷上下文"]
```

### 4.2 系统架构图：两个仓库与外部资源

```mermaid
flowchart LR
  User["学习者 / 维护者"] --> CLI["Anki Python CLI"]
  subgraph AnkiRepo["anki-pipeline 仓库"]
    CLI --> Storage["store / migration / translations"]
    Storage --> StudyDB[("新学习 SQLite")]
    CLI --> Enrich["lexical / exam / etymology 构建模块"]
    Enrich --> Templates["HTML / CSS / JS 模板"]
    Templates --> APKG["APKG"]
    Templates --> Static["完整网页 / ZIP"]
  end
  External["本机第三方词典 / 音频 / ECDICT / 词源"] -->|"只读"| Enrich
  subgraph ExamRepo["exam-library 配套仓库"]
    Structured["结构化试卷 JSON / JSONL"] --> QB[("可再生题库 SQLite")]
    Reviewed["已审译文 / chunk / 句子索引"] --> Published["本机静态译文和定位资源"]
    QB --> Service["本机 8765 静态服务 + 只读 API"]
    Published --> Service
    Original["原版 SVG / 重排 HTML / 图片"] --> Service
  end
  Structured -->|"构建时读取"| Enrich
  Reviewed -->|"构建时读取"| Enrich
  APKG --> Native["Anki 客户端"]
  Static --> Browser["本机网页预览"]
  Native -->|"学习时链接"| Service
  Browser -->|"学习时链接"| Service
  Native --> Eudic["已安装欧路协议"]
  Browser --> Eudic
```

### 4.3 ER 图：新版 Anki 学习数据库

```mermaid
erDiagram
  CARDS ||--o{ SENTENCES : contains
  CARDS ||--o| LEGACY_ROWS : preserves
  CARDS {
    text id PK
    text sheet
    text lesson
    text position
    text word
    text phonetic
    text definition
    text simple_definition
    text level
    text word_forms
    text audio_filename
  }
  SENTENCES {
    text id PK
    text card_id FK
    text text
    text source
    text translation
    int original_number
    int accepted
    text review_reason
  }
  LEGACY_ROWS {
    text card_id PK,FK
    text payload
  }
  METADATA {
    text key PK
    text value
  }
  EVENTS {
    int id PK
    text happened_at
    text action
    text details
  }
```

`metadata` 与 `events` 是独立配置 / 审计表，不存在指向每张卡的外键。词典、真题新例句和词源在生成时组合到字段，不虚构已经写入这个 schema 的额外表。

### 4.4 ER 图：真题题目与来源块

```mermaid
erDiagram
  PAPERS ||--o{ QUESTIONS : owns
  PAPERS ||--o{ SOURCE_BLOCKS : preserves
  QUESTIONS ||--o{ OPTIONS : contains
  QUESTIONS ||--o| ANSWERS : has
  QUESTIONS ||--o| SCOREABILITY : checked
  QUESTIONS ||--o{ QUESTION_SOURCE_BLOCKS : orders
  QUESTIONS ||--o{ CONTEXT_SOURCE_BLOCKS : shares
  SOURCE_BLOCKS ||--o{ QUESTION_SOURCE_BLOCKS : quoted
  SOURCE_BLOCKS ||--o{ CONTEXT_SOURCE_BLOCKS : quoted
  PAPERS ||--o{ LABELS : categorizes
  QUESTIONS ||--o{ QUESTION_LABELS : joins
  LABELS ||--o{ QUESTION_LABELS : joins
  PAPERS {
    text id PK
    text category
    text title
    int year
    text source_original
    text source_reflow
    text json_path
  }
  QUESTIONS {
    text id PK
    text paper_id FK
    text number
    text question_type
    int ordinal
    text stem
    int in_bank
  }
  OPTIONS {
    text id PK
    text question_id FK
    text label
    text source_label
    int default_position
    int source_position
    int is_correct
  }
  ANSWERS {
    text question_id PK,FK
    text value
    text solution
    text explanation
    text status
    text source_document_id FK
  }
  SOURCE_BLOCKS {
    text id PK
    text paper_id FK
    int ordinal
    text text
    text content_html
  }
```

`OPTIONS.is_correct` 的值还可以是 NULL；ER 图只写字段类型，三态语义见 3.12。关联表保留顺序，避免把共享文章当作每题各复制一份失去原位置。

### 4.5 ER 图：真题语义层与可审计来源

```mermaid
erDiagram
  PAPERS ||--o{ SEMANTIC_NODES : contains
  SEMANTIC_NODES o|--o{ SEMANTIC_NODES : parent
  SEMANTIC_NODES ||--o{ CONTENT_UNITS : contains
  CONTENT_UNITS ||--|| UNIT_PROVENANCE : traces
  SOURCE_BLOCKS o|--o{ UNIT_PROVENANCE : original
  SEMANTIC_NODES ||--o{ QUALITY_ISSUES : reports
  SEMANTIC_NODES ||--o{ SEMANTIC_LINKS : from_node
  SEMANTIC_NODES ||--o{ SEMANTIC_LINKS : to_node
  SEMANTIC_NODES {
    text id PK
    text paper_id FK
    text parent_id FK
    text node_type
    int ordinal
    text question_id FK
    text option_id FK
  }
  CONTENT_UNITS {
    text id PK
    text node_id FK
    text unit_type
    text text
    text content_html
  }
  UNIT_PROVENANCE {
    text content_unit_id PK,FK
    text source_block_id FK
    text json_path
    text source_hash
  }
  SEMANTIC_LINKS {
    text from_node_id PK,FK
    text to_node_id PK,FK
    text link_type PK
    int ordinal
  }
  QUALITY_ISSUES {
    text id PK
    text node_id FK
    text issue_code
    text detail
  }
```

来源是 `source_block_id` 或 `json_path` 二选一，受 schema 约束。语义层是对已有题表的附加关系，并非另一个用户成绩数据库。

### 4.6 时序图：构建与发布产物

```mermaid
sequenceDiagram
  participant Owner as 维护者
  participant CLI as anki-pipeline
  participant DB as 新学习库
  participant Inputs as 外部词典与已审真题
  participant Renderer as packaging / web_preview
  participant Files as output 文件
  Owner->>CLI: offline-bundle --file 新包路径
  CLI->>DB: 只读质量检查与 logical_digest
  DB-->>CLI: 原卡片与摘要
  CLI->>Inputs: 读取词典、索引、补全、词源
  Inputs-->>CLI: hash 绑定的有效输入
  CLI->>Renderer: 组合显示、统计、源链接
  Renderer->>Files: 生成临时 APKG 并核对来源 / 数据摘要
  alt APKG 校验通过
    Renderer->>Files: 原子发布 APKG
    Renderer->>Files: 生成与校验网页目录
    alt 网页校验通过
      Renderer->>Files: 切换网页入口
      Renderer->>Files: 生成与校验 ZIP
      alt ZIP 校验通过
        Renderer->>Files: 原子发布 ZIP
        CLI-->>Owner: 整套完成报告
      else ZIP 失败
        CLI-->>Owner: 保留旧 ZIP；已发布 APKG / 网页可能为新版
      end
    else 网页失败
      CLI-->>Owner: 保留旧网页入口；已发布 APKG 可能为新版
    end
  else APKG 失败
    CLI-->>Owner: 不发布 APKG，后续产物未执行
  end
```

### 4.7 时序图：双向补全的真实点击跳转

```mermaid
sequenceDiagram
  participant Learner as 学习者
  participant Card as 词卡例句
  participant Browser as 浏览器
  participant Index as 已审静态索引
  participant Reader as 重排 / 整卷阅读器
  Learner->>Card: 查看同题同正确项的合并例句
  Learner->>Card: 点击跳转图标
  Card->>Browser: URL + 原句 pins + 双向 context
  Browser->>Reader: 打开对应试卷
  Reader->>Index: 校验句子、英文 hash、review hash
  Index-->>Reader: 题干与正确选项的原引用
  alt 引用及原文都匹配
    Reader->>Reader: 定位所属题干顶部
    Reader->>Reader: 框出题干与正确选项
    Reader-->>Learner: 看见完整原题，不固定标黄单词
  else 过期或来源缺失
    Reader-->>Learner: 定位失败 / 不套用相似文本
  end
```

普通单向链接不携带上述双向 context，不因此把所有题干与全部选项都框起来。

### 4.8 时序图：译文 CSV 的安全回填

```mermaid
sequenceDiagram
  participant Owner as 维护者
  participant CSV as 工作 CSV
  participant Validate as translations.py
  participant Backup as SQLite 备份
  participant DB as 新学习库
  Owner->>CSV: 只修改 translation 列
  Owner->>Validate: import-translations
  Validate->>DB: 读取 ID、原文、hash、修订
  DB-->>Validate: 当前行状态
  Validate->>Validate: 验证整表、重复 ID 与过期内容
  alt 整表有效
    Validate->>Backup: 建立完整备份
    Validate->>DB: BEGIN IMMEDIATE + 重查 + 更新
    DB-->>Validate: COMMIT
    Validate-->>Owner: 成功数量与事件
  else 任意一行无效
    Validate-->>Owner: 拒绝导入，活动库不部分更新
  end
```

### 4.9 差异流程图：只看选项与有上下文的学习

```mermaid
flowchart LR
  Input["原阅读选项命中目标词"] --> Old["早期显示：只有选项半句"]
  Input --> Verify["当前：唯一题目、来源与译文核验"]
  Verify --> Gap{"题干有唯一空位?"}
  Gap -->|"是"| Completed["当前候选填入题干，插入处下划线"]
  Gap -->|"否"| Separate["原问题 + 当前候选分段"]
  Completed --> Translation["完整审校中文 + 候选身份"]
  Separate --> Translation
  Translation --> Count["词频仍使用原印刷位置"]
  Translation --> Link["原题上下文跳转与外框"]
  Old --> Limited["缺问题，不便理解"]
```

这张图是功能差异，不表示可以用新组合反向改写原卷。

### 4.10 数据流图：计数和显示分离

```mermaid
flowchart TD
  Printed["真实印刷句子、题干、选项"] --> Canonical["规范来源身份去重"]
  Canonical --> Forms["明确词形 + 完整 token + 已审排除"]
  Forms --> Occurrences["不同原位置出现次数"]
  Occurrences --> Frequency["F 次 / P 套 / 半星"]
  Forms --> Derive["回填题干或恢复选项上下文"]
  Reviewed["批准组合译文"] --> Derive
  Derive --> DisplayDedup["同题同正确组合的双向显示去重"]
  DisplayDedup --> Examples["展示例句列表与序号"]
  DisplayDedup --> Context["保留两部分原引用"]
  Context --> Frames["跳转后题干和正确项双框"]
  Derive -. "插入副本不返回词频计数" .-> Occurrences
```

虚线在这里表示禁止把显示副本重新当作来源输入；实际词频只走上方的原位置路径。

### 4.11 状态图：hover、点击固定与取消

```mermaid
stateDiagram-v2
  [*] --> Plain
  Plain --> Hovered: 鼠标进入英文或中文有效 chunk
  Hovered --> Plain: 鼠标离开当前对应
  Hovered --> Pinned: 点击有效 chunk
  Plain --> Pinned: 手机或鼠标点击有效 chunk
  Pinned --> Pinned: 点击另一个有效对应
  Pinned --> Plain: 再点相同对应 / 空白 / Esc
  Hovered --> Plain: 切卡或翻面清理
  Pinned --> Plain: 切卡或翻面清理
  state Plain {
    [*] --> NoActivePair
  }
```

英文和中文在同一例句作用域中触发已有 ID。链接、音频与输入控件走其自身事件，不进入 chunk 选择流程。

### 4.12 状态图：Anki WebView 与倒计时生命周期

```mermaid
stateDiagram-v2
  [*] --> Unbound
  Unbound --> FrontReady: 当前正面完成渲染
  FrontReady --> BackReady: 显示答案
  BackReady --> FrontReady: 新卡正面
  FrontReady --> Rebind: 节点或 body 状态被客户端重置
  BackReady --> Rebind: 节点或 body 状态被客户端重置
  Rebind --> FrontReady: 识别当前正面并恢复
  Rebind --> BackReady: 识别当前背面并恢复
  FrontReady --> Cleanup: 切换到无本模板的笔记
  BackReady --> Cleanup: 切换到无本模板的笔记
  Cleanup --> Unbound: 清定时器、footer 和旧包装
```

有效 footer 放在当前例句 / 翻译内容末尾，内容区域保持正常高度。这个状态图描述脚本资源生命周期，不是 Anki 的新卡 / 学习 / 复习调度状态。

### 4.13 状态图：重绘首屏与手动切换

```mermaid
stateDiagram-v2
  [*] --> OriginalVisible
  OriginalVisible --> RedrawLoading: 主动请求已绑定重绘
  RedrawLoading --> RedrawVisible: load 成功且 naturalWidth 有效
  RedrawLoading --> OriginalVisible: error 或资源不可用
  RedrawVisible --> OriginalVisible: 查看原图
  OriginalVisible --> RedrawVisible: 已加载时查看重绘图
```

初次请求不依赖隐藏图的懒加载；三张连续截图应验证首次进入与切回后的尺寸一致。

### 4.14 类图：有实际类型的核心模块

```mermaid
classDiagram
  class Config {
    +Path project_root
    +Path database
    +Path output
    +str deck_name
    +str deck_identity_name
    +str exam_reader
    +str exam_sentence_source
  }
  class Alignment {
    +tuple en
    +tuple zh
    +str relation
  }
  class Snapshot {
    +Path path
    +str sha256
    +unchanged()
  }
  class BuildStats {
    +int papers
    +int question_records
    +int source_blocks
    +int options
  }
  class CLI {
    <<module>>
    +parser()
    +run(args)
  }
  class Store {
    <<module>>
    +connect()
    +transaction()
    +backup_database()
    +restore_database()
  }
  class ExamLibrary {
    <<module>>
    +library_examples()
  }
  class Packaging {
    <<module>>
    +build_package()
    +render_preview()
  }
  CLI --> Config : uses
  CLI --> Store : reads_or_writes
  CLI --> ExamLibrary : derives_examples
  CLI --> Packaging : creates_output
  ExamLibrary --> Snapshot : validates_sources
  ExamLibrary --> Alignment : validates_ranges
```

`CLI`、`Store`、`ExamLibrary`、`Packaging` 明确标为模块，不是假装源码里存在同名面向对象服务类。`BuildStats` 是配套题库的真实 dataclass。

### 4.15 部署图：本机与手机的地址边界

```mermaid
flowchart TB
  subgraph Mac["同一台本机"]
    Inputs["本机资料目录"] --> Builder["Python 构建"]
    Builder --> Package["本地 APKG"]
    Builder --> PreviewFiles["本地网页输出 / ZIP"]
    Package --> Anki["Anki 桌面客户端"]
    PreviewFiles --> PreviewServer["127.0.0.1:8771 或 ZIP 随机端口"]
    PreviewServer --> Browser["桌面浏览器"]
    ExamFiles["exam-library 静态页 + 可再生 SQLite"] --> ExamServer["127.0.0.1:8765"]
    Browser -->|"原句链接"| ExamServer
    Anki -->|"原句链接"| ExamServer
  end
  Package --> Mobile["另一个设备的 Anki，兼容性单独验证"]
  Mobile --> Localhost["该设备 localhost 指向它自己"]
  ExamServer -. "默认不监听局域网；需要另行配置" .-> Mobile
  Repo["GitHub 公开源码 + 文档 + 截图"] --> Builder
```

这张图没有自动同步箭头，因为源码构建、Anki 同步和真题网络访问属于不同功能。用户要在远端设备打开原卷时，需要实际可达地址，不能沿用本机 localhost 假装可达。

### 4.16 测试与交付流程图

```mermaid
flowchart TD
  Diff["明确实际代码 / 输入差异"] --> Python["Python 单元与集成：匹配、事务、来源、包装"]
  Diff --> DOM["Node / jsdom：事件、布局结构、生命周期"]
  Python --> Install["独立 wheel 安装及模板资源"]
  DOM --> Runtime["Safari / 浏览器真实交互"]
  Install --> Build["本机完整输入构建与报告"]
  Build --> Backend["隔离 Anki 后端导入：身份、媒体、进度样本"]
  Build --> Reviewer["原生 reviewer 组件渲染"]
  Runtime --> Clicks["多个点击前后：原句、双向框、答案、图片"]
  Reviewer --> Screens["统一截图目录 + 功能说明"]
  Clicks --> Screens
  Backend --> Evidence["限定范围的核验结果"]
  Screens --> Review["一次围绕实际 diff 的独立审查"]
  Evidence --> Review
  Review --> PR["源码版本 PR"]
  PR --> Decision["另行授权的合并 / tag / Release"]
```

单元测试、后端导入和离屏渲染不能替代未运行的真实手机 / 平板或用户档案同步。PR 的文档应保留这些范围，而不是将所有箭头简化成一句“全部通过”。

### 4.17 配套题库构建与答案读取时序

```mermaid
sequenceDiagram
  participant Owner as 维护者
  participant Serve as serve_exam_library.py
  participant Builder as build_question_database.py
  participant JSON as 结构化 JSON / JSONL
  participant DB as 本地题库 SQLite
  participant UI as 整卷练习页
  Owner->>Serve: 启动服务
  Serve->>DB: 检查存在、模式与输入更新时间
  opt 数据库缺失或输入更新
    Serve->>Builder: 重建可再生数据库
    Builder->>JSON: 读取审计、原卷和来源 hash
    JSON-->>Builder: 可信输入
    Builder->>DB: 临时库 + 外键 / 完整性检查 + 原子替换
  end
  UI->>Serve: 请求题文与选项
  Serve->>DB: 按原序或 seed 查询，隐藏正确标记
  DB-->>UI: 固定 ID 题目和选项
  UI->>Serve: 点击查看答案
  Serve->>DB: 请求答案及可信 correctOptionIds
  DB-->>UI: 答案材料或明确未知状态
```

### 4.18 跨仓库来源关系图

```mermaid
flowchart LR
  Paper["结构化 paper ID"] --> Block["原 block / 原选项"]
  Block --> Source["原句 ID + 范围 + English hash"]
  Source --> Translation["准确译文 + translation hash"]
  Translation --> Review["批准审校 + reviewedContentHash"]
  Review --> Index["可用句子索引"]
  Index --> Completion["已审题干 / 选项组合"]
  Completion --> Card["词卡字段与插入下划线"]
  Source --> Frequency["原位置次数"]
  Source --> Link["原句导航 pins"]
  Completion --> Context["仅双向合并时的两组 context refs"]
  Link --> Reader["原卷阅读器核对"]
  Context --> Reader
  Reader --> Framing["实际题干 / 选项外框"]
```

这些是应用层版本化引用，不是两个仓库数据库之间的外键。图中没有自动生成译文或自动批准箭头；译文和批准记录必须来自已有明确流程。
