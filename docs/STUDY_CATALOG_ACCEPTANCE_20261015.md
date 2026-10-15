# PostgreSQL 总库：2026-10-15 阶段验收记录

本记录索引当前真实产物与测试范围，不是发布声明或最终完成证明。
工作分支为 `feat/unified-study-database-20261015`；已提交节点截至 `37a2a3d`，后续变更待主线程集中复核和 Git checkpoint。
数据库是本机 PostgreSQL 17 的 `anki_study_catalog` / `study_catalog`，专用普通角色；
未写真实用户 Anki 档案，未覆盖原库/原包、切换旧书架或更新远端发行。

## 1. 状态门槛

| 范围 | 当前结论 | 不延伸的结论 |
|---|---|---|
| 指定五源迁入 | 三 APKG、legacy 与 semantic 都 complete，完整历史表行已迁入 | 不以迁移结束报告代替全库深校验和完整恢复 |
| 三份完整 APKG 基线 | 全部 ZIP 成员未压缩字节与原输入一致 | 不要求压缩封装字节相同，不声称包体进一步瘦身 |
| 临时原生 Anki | 三包更新/重复导入、身份和学习状态、全媒体及12卡模板样例有证据 | 不等于真实用户档案同步、逐卡屏幕或手机验收 |
| 两书全网页静态对账 | 刘晓艳/2026全部GUID、模板、单元、页面、媒体与宿主源资源对账 | 不代表后续导航/性能改动已通过实际交互 |
| 数学与新增来源 | 一note两模板原生样例、此前Safari公式观察、IELTS/generic来源专项测试 | 不等于所有数学模型、全部来源资料或手机平台已验 |
| 修订与版本接口 | 隔离PG专项测试、连续来源链、交叉导入及失效请求拒绝有证据 | 实际三书master没有写入测试语义修订；当前集中复核尚未结束 |
| 完整备份→恢复→独立对账 | **进行中，待实际完整报告补齐** | 空库基线和小schema恢复测试不能代替完整主库恢复 |
| 最新网页交互/性能、独立审查 | **进行中，按主线程最终结果补齐** | 不把旧样例、静态测试或历史全绿外推为最新全量通过 |

## 2. 迁移与输入封印

`migration-v1.json` 的基线为：3 books、227 units、15,174 notes、6,785 words、101,723 components、
3,667,930 objects、138,464 每书资源别名、82,171 唯一媒体内容、13,212 analyses、55,302 dictionary_senses、
11,558 sentences、154,015 tokens、292,597 decisions、55,295 chunks、3,029,869 archive_rows。
这些是该报告时点的表行数，注册、后续事件与对象可能使实时计数增长；它们不是物理词频合计。
语义原始表完整含 30,256 snapshots、1,225,632 occurrences 与同数 assignments。
五源 complete 及其逐表行数在报告内，原表定义、原列、全部原始行和摘要保留。

- 迁移输入清单 SHA256：`9b6a94131a135db8fa20b9382e85395be8c04b781c40167191ade9c9fb46eda7`。
- 语义源 `data/sense-frequency-optimized-20261013.sqlite3` SHA256：`897cc6478d5901ce5d250a7e3486b363937d8fc3985091b3b347a8f46e2c5d7f`。
- 原 APKG 输入摘要、生成包摘要和导入前后不变检查分别见三份原生报告；未用重压缩包的总文件SHA代替成员字节检查。
- 完整原目录保留与1960旧词卡来源绑定已做；22个作者换行/`<br>`采用精确可逆绑定，原字段未改。
- 本批保留 `as convenient and provocative` 的既有来源异常标记，没有重新判定其唯一语法或词义。

## 3. 完整包与成员字节

以下是从 PostgreSQL 导出的**未做语义/运行时修订基线**。字节数是产物实测值，不是承诺未来修订包大小不变。

| 书籍 | 笔记/卡片 | 生成文件（均在 `output/study-catalog-20261015/`） | 字节数 | 生成包SHA256 |
|---|---:|---|---:|---|
| 刘晓艳2027 | 1960/1960 | `master-liuxiaoyan2027-v1.apkg` | 85,656,300 | `2083d740dca9cacd60bdc3c7fb432f35b8885549874296809c053b2e9a0efb33` |
| 红宝书2026 | 6682/6682 | `master-redbook2026-v1.apkg` | 402,079,704 | `71d18c24d02a8df611a1876e00c10a2edf254798b61f7e5b4f94e4a5501bc991` |
| 红宝书2027 | 6532/6532 | `master-redbook2027-v1.apkg` | 357,155,601 | `85801edc7c85225958a5c46e03390e1841798066fcdf424cb693d450842e2152` |

`apkg-source-member-parity-v1.json` 逐个流式比较全部未压缩 ZIP 成员：刘晓艳6534、2026版66425、2027版65513。
比较覆盖 collection、media索引及全部媒体/其他成员，不只是前几张卡或一个样例文件。
源字段、原媒体、model/deck/ID和排程封存由此可逆保留。压缩容器允许不同，不能写“源包文件完全相同”。

## 4. 原生 Anki 的实际范围

验收脚本为 `scripts/verify_study_catalog_native.py`，只接受源包、候选包和新报告路径，
内部创建 TemporaryDirectory 中的集合。流程是源包导入、真实复习一张测试卡、设置停学/旗标，
再导入候选两次，比较所有note身份及卡片状态、revlog；逐个检查媒体摘要和缺失，渲染最多12张正反面模板。
“模板渲染”是 Anki API 生成非空问/答HTML，不是浏览器执行全部脚本或手机触摸验收。

| 报告 | 全量与样例范围 | 正确字段结论 |
|---|---|---|
| `liu-native-qa-v1.json` | 1960 notes/cards、6530媒体、12卡模板，重复更新2次 | 当时原文比较通过，媒体精确一致 |
| `redbook2026-native-qa-v2.json` | 6682 notes/cards、66423媒体、12卡模板，重复更新2次 | **原文相同或其NFC等价形式**；旧 `fields_and_media_exact` 字段措辞过宽，不能据此声称所有导入后字段字节相同，也没有可推断的NFC差异数量 |
| `redbook2027-native-qa-v2.json` | 6532 notes/cards、65511媒体、12卡模板，重复更新2次 | 65,313字段值中65,312原文相等、1个值被Anki做NFC规范化；6532 notes中6531原文相等、1 note规范化 |

三次均记录媒体缺失0、原包/候选文件未被验收脚本改动、用户档案未修改。
旧失败日志仍保留作诊断，不能覆盖成绿色报告；ZIP成员原字节验收与原生NFC是两种独立结论。

## 5. 数学、雅思及公共修订

数学v2样例为无Word字段的一条note、两张正向/反向卡，修订共享Answer后，APKG与网页都保留两张卡。
`math-native-qa-v2.json` 记录两次更新/重复导入、两卡模板和学习状态检查。
此前本会话的Safari人工观察在 `qa-math-web-v2/index.html` 验证了正向公式、答案、反向公式及翻面；
这是此前主线程的样例观察，不是本文编写者新增的全量浏览器结果，也不是手机Anki数学验收。

独立wheel构建与临时target安装验证固定MathJax3.2.2的25个资源及SOURCE清单，共26文件，
每个SHA符合清单；安装后CLI帮助启动成功，原venv未改。Anki使用原生数学宿主，网页无需CDN。
来源专项测试证明 `study:ielts:...` 使用既有语义封印/物理计数，显式来源证据变动失效，
旧考研payload/snapshot摘要保持不变；未注明年份显示文字，不拿0或书名猜测值冒充真实年份。

专项证据覆盖：

- 词典义项、原句/译文/chunk与转归的跨原书/映射书修订，完整旧依据和原生Examples跟随当前事实。
- 过期/缺失/无关scope、来源或候选封印失效、晚阶段编译错误整事务拒绝，不能只写成功一本。
- 单位置转归只改变源/目标归属，保留物理次数；同段同义展示与不同义项分条不反过来修改次数。
- note/model同秒连改和A→B→A回退，原生版本仍推进；新映射书、资源反向依赖/循环和语义→运行时交叉导入保持一致。
- 来源链25次增长测试与22次**隔离真实PG提交**分别验证平坦保留历史；不是“在实际三书主库改了22次”。
- 新原生分组保留每个目标、双语细块、成员来源/跳转封印与完整审核，不把原块替换成整段粗块。

最后专项日志的覆盖可能重叠，不能相加当总测试数；本阶段集中回归尚未结束。
例如 `/tmp/study-catalog-native-group-integration-v1.log` 的11项合集曾有candidate旧记录缺失错误，
后续 `/tmp/study-catalog-candidate-sequence-v2.log` 目标项已通过；这不等于原11项合集已经重新全绿。
此前全仓1236测试运行在外部词典/审校快照fixture处有失败和错误，不能把那次运行标为通过；
最新源码的最终集中结果待主线程补齐。

## 6. 全书网页与后续宿主范围

两本非iCloud完整目录：

- `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-liuxiaoyan2027-web-v1`
- `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v1`

二者revision均为11，COMPLETE存在；静态对账分别覆盖1960与6682张实际卡的全部GUID、native_id、模板序号/名称、
单元、URL、非空页面及精确页面集合。原媒体为6530/66423；额外宿主源CSS/JS为2/8，
因此物理media文件为6532/66431，全部SHA正确。原模型模板、CSS和外提脚本文本未改；
网页外壳与资源交付是宿主适配，不能说整个网页HTML等于原卡HTML。

2027完整网页已构建于 `output/study-catalog-20261015/master-redbook2027-web-v1`。
主线程正在统一处理最新导航/入口/性能及交互scope；这些变化不由前述旧目录静态报告自动验收。
本次发现过刘晓艳22个`<br>`的侧栏字面显示问题，属于通用宿主显示层，原Word字段应保留；
修复与实际UI结果应跟随最终导航验收记录，不靠修改来源内容解决。

这些是数据库版本快照。后续分类、内容或宿主更新不自动重写旧目录；当前快照与最新master必须明确区分。
三书入口、搜索/单元过滤、切卡/翻面、音频、细块联动和移动尺寸性能的最新实际结果仍待主线程补入。
没有新增“手机全量已验”结论。

## 7. 完整恢复与最终集中复核：待补

迁移前备份 `backups/study-catalog-20261015/catalog-20261015T011656-220779b4.pg.jsonl.gz`
是空库基线；它只能用于说明迁移前状态，不能证明当前数百万对象可完整恢复。
当前完整备份、向新schema恢复、独立逐表行指纹/序列对账和全库深校验仍在进行。
恢复流式指纹、二进制/浮点、重复行及失败回滚测试是前置证据，不替代实际完整库报告。
恢复对账中的序列范围是未来插入安全性；备份 v1 没有保存历史 sequence 高水位，不能扩大成历史序列状态完全还原。

主线程完成后须补：实际备份路径和SHA、恢复schema、备份/恢复表数与行数、独立对账报告SHA、
深校验报告、当前源码集中测试/独立审查范围，以及最终Git checkpoint。
在这些证据齐全前不将总目标标为完成；遇到已确认live job保持同一作业等待，观察超时不当作失败重启。

## 8. 本地证据索引与SHA256

以下文件为本机实际生成证据；大型数据、卡包、机器日志和临时运行目录不提交Git。
此Markdown保留路径、摘要和已观察范围，不能把本地路径当作已发布下载链接。
报告改变或代码/输入/运行环境变动后，先核对相应范围是否仍有效再复用结论。

| 证据 | 实际本地路径（项目相对路径或绝对路径） | 文件SHA256 |
|---|---|---|
| 迁移与全表历史行 | `output/study-catalog-20261015/migration-v1.json` | `a2a1bf5a7a5b37b8cac68ebc245c636b0f61fb575b1ae8ae3ce471591ba77716` |
| 三包全部ZIP成员 | `output/study-catalog-20261015/apkg-source-member-parity-v1.json` | `42eb08b6bfdbcc2a4c8fb46ca1f6c6740fccb265171601a4bec0eed635112e5d` |
| 刘晓艳原生完整包 | `output/study-catalog-20261015/liu-native-qa-v1.json` | `1ecef80c9d0c2812c505e1801d1c42aa31b844123507d48a6ac92231b9bf137a` |
| 2026原生完整包；旧措辞限定 | `output/study-catalog-20261015/redbook2026-native-qa-v2.json` | `c2049c9d9d7ee5478e4ff0821d5064b9d915b575764476305ccde77a1166476d` |
| 2027原生完整包；逐字段NFC计数 | `output/study-catalog-20261015/redbook2027-native-qa-v2.json` | `4e570b2e3c99eff19dca43886aee5046ed6e5e85c105ae39261fd151490d5511` |
| 数学构建样例 | `output/study-catalog-20261015/qa-math-build-v2.json` | `49787e09ea9293fdfe143d4abdbef7e1a405eb11d3277108540c36fba8470e0b` |
| 数学原生双模板样例 | `output/study-catalog-20261015/math-native-qa-v2.json` | `e1834fc44aba4f23251ec3e5f166307f310bbdf5d567e882a87dcec38e645bcb` |
| wheel数学资源安装 | `output/study-catalog-20261015/wheel-math-assets-qa-v1.json` | `02f626c620a0002c25827400cd3e580974f536f5f13e983b105acd7f6c3e4d85` |
| 原生note/model回退 | `output/study-catalog-20261015/native-note-model-reverts-v1.json` | `f4443cf922048ba39cda0b82a60ab67fb15d8b233f09ffb010246d2a9fb9cd73` |
| 原生运行时版本 | `output/study-catalog-20261015/native-runtime-revisions-v2.json` | `71747f3e9d6d24ebeba3bde8e1f540ee9cbd68f60ea95ba5637e3deff8fffe23` |
| 运行时依赖 | `output/study-catalog-20261015/native-runtime-dependencies-v2.json` | `207f8eefdfb2329f32af9b7dc311de08627e2129634d522b25c39925b0cbf58e` |
| 语义/运行时交叉原生导入 | `output/study-catalog-20261015/native-runtime-semantic-sequence-v1.json` | `18c436f6cb0f968eb12e4f249a916aeff3275f8032efe4a84e81d77acdeb16bc` |
| 25次平坦来源链增长 | `output/study-catalog-20261015/source-chain-growth-v1.json` | `edd9e7d6b1de02afe2c0ed7d9d2826c10ed8343b37b844df3a5ae5c20fe80d91` |
| 刘晓艳全网页静态对账 | `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-liuxiaoyan2027-web-v1.qa.json` | `e8db99cb5507b3fe5a79467cf4528c7a9cc8834d87a326f564ce00af2fc09c90` |
| 2026全网页静态对账 | `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v1.qa.json` | `8be37272af263da84ef38157de46183c9426c6abe0ae4e6d2cbc4826d98a2e39` |

关键专项日志另位于 `/tmp`，不是持久发布附件：`study-catalog-flat-source-api-22-v1.log`、
`study-catalog-content-flat-final-v1.log`、`study-source-identity-green.log`、`study-native-groups-green.log`、
`study-native-groups-regression.log`、`study-native-model-note-revert-tests-final-20261015.log`、
`study-native-versions-runtime-final-tests-20261015.log` 及前述candidate/integration日志。
它们用于限定本次检查过程；最终可交付状态以主线程补入的集中证据和实际产物为准。
