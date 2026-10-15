# PostgreSQL 总库：2026-10-15 阶段验收记录

本记录索引当前真实产物与测试范围，不是发布声明或最终完成证明。
工作分支为 `feat/unified-study-database-20261015`；共同修订与网页宿主节点为 `415c5dc`，服务性能节点为 `b48e601`。
数据库是本机 PostgreSQL 17 的 `anki_study_catalog` / `study_catalog`，专用普通角色；
未写真实用户 Anki 档案，未覆盖原库/原包、切换旧书架或更新远端发行。

## 1. 状态门槛

| 范围 | 当前结论 | 不延伸的结论 |
|---|---|---|
| 指定五源迁入 | 三 APKG、legacy 与 semantic 都 complete，完整历史表行已迁入 | 不以迁移结束报告代替全库深校验和完整恢复 |
| 三份完整 APKG 基线 | 全部 ZIP 成员未压缩字节与原输入一致 | 不要求压缩封装字节相同，不声称包体进一步瘦身 |
| 临时原生 Anki | 三包更新/重复导入、身份和学习状态、全媒体及12卡模板样例有证据 | 不等于真实用户档案同步、逐卡屏幕或手机验收 |
| 三书全网页静态对账 | 刘晓艳/2026/2027全部GUID、模板、单元、页面、媒体与宿主源资源对账 | 不代表逐卡屏幕或真实手机全量验收 |
| 数学与新增来源 | 一note两模板原生样例、此前Safari公式观察、IELTS/generic来源专项测试 | 不等于所有数学模型、全部来源资料或手机平台已验 |
| 修订与版本接口 | 隔离PG专项测试、连续来源链、交叉导入及失效请求拒绝有证据；独立复核已关闭本轮P1/P2 | 实际三书master没有写入测试语义修订 |
| 完整备份→恢复→独立对账 | **实际完成**；完整7,131,700,562字节备份恢复到新schema，24表8,118,998行完整payload对账通过 | 序列仅核未来插入安全；不代替语义正确性或客户端验收 |
| 实际主库深校验 | `master-deep-verification-v1.json` 的 `ok=true`，完整解压/摘要校验3,667,957对象、全部历史表行流和归一化物理行数 | 不代替备份恢复后逐表完整payload对账 |
| 最新网页交互/性能、独立审查 | 三书目录、翻面、键盘、音频、细块及移动尺寸已有实际记录；旧版总书架已恢复并实点进入新版 | 不冒称真实手机冷启动、逐卡交互或全仓测试全绿 |

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
当前源码的安装验收为 `wheel-current-install-qa-v4.json`：只从跟踪的当前源码建立干净临时构建目录，
在仓库外加载实际安装target，131个包内文件与源码一致，25个公式资源摘要符合SOURCE，
typed修订与恢复命令可用。v4覆盖本次共享宿主、原子正文挂载和统一导出接线；后续改动须重新确认适用范围。
来源专项测试证明 `study:ielts:...` 使用既有语义封印/物理计数，显式来源证据变动失效，
旧考研payload/snapshot摘要保持不变；未注明年份显示文字，不拿0或书名猜测值冒充真实年份。

专项证据覆盖：

- 词典义项、原句/译文/chunk与转归的跨原书/映射书修订，完整旧依据和原生Examples跟随当前事实。
- 过期/缺失/无关scope、来源或候选封印失效、晚阶段编译错误整事务拒绝，不能只写成功一本。
- 单位置转归只改变源/目标归属，保留物理次数；同段同义展示与不同义项分条不反过来修改次数。
- note/model同秒连改和A→B→A回退，原生版本仍推进；新映射书、资源反向依赖/循环和语义→运行时交叉导入保持一致。
- 来源链25次增长测试与22次**隔离真实PG提交**分别验证平坦保留历史；不是“在实际三书主库改了22次”。
- 新原生分组保留每个目标、双语细块、成员来源/跳转封印与完整审核，不把原块替换成整段粗块。

最后专项日志的覆盖可能重叠，不能相加当总测试数。集中复核的最终范围包括：
旧/当前来源与转归43项通过、2项缺外部样本跳过，原生历史链独立31项、目录15项、
网页8项、来源修订独立11项、静态映射独立14项通过；首次别名标准专项5项通过。
这些范围不能扩大为全仓全部测试通过。
例如 `/tmp/study-catalog-native-group-integration-v1.log` 的11项合集曾有candidate旧记录缺失错误，
后续 `/tmp/study-catalog-candidate-sequence-v2.log` 目标项已通过；这不等于原11项合集已经重新全绿。
此前全仓1236测试运行在外部词典/审校快照fixture处有失败和错误，不能把那次运行标为通过；
独立 reviewer 对实际 diff 的本轮 P1/P2 已关闭；实际主库深校验通过，完整备份恢复对账仍等待实际结果。

## 6. 全书网页与后续宿主范围

两本非iCloud完整目录：

- `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-liuxiaoyan2027-web-v1`
- `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v1`

二者revision均为11，COMPLETE存在；静态对账分别覆盖1960与6682张实际卡的全部GUID、native_id、模板序号/名称、
单元、URL、非空页面及精确页面集合。原媒体为6530/66423；额外宿主源CSS/JS为2/8，
因此物理media文件为6532/66431，全部SHA正确。原模型模板、CSS和外提脚本文本未改；
网页外壳与资源交付是宿主适配，不能说整个网页HTML等于原卡HTML。

2027完整网页构建于 `output/study-catalog-20261015/master-redbook2027-web-v1`，同样revision为11。
`master-redbook2027-web-v1.qa.json` 已逐一核对6532张卡及全部65520个媒体文件：
其中65511个原资源别名、3个model CSS、6个独立脚本，全部SHA精确一致，原模板一致。
后续导航/入口/性能及交互另由6.1节记录，不能用静态报告代替交互。
本次发现过刘晓艳22个`<br>`的侧栏字面显示问题，属于通用宿主显示层，原Word字段应保留；
修复与实际UI结果应跟随最终导航验收记录，不靠修改来源内容解决。

这些是数据库版本快照。后续分类、内容或宿主更新不自动重写旧目录；当前快照与最新master必须明确区分。
三书入口、搜索/单元过滤、切卡/翻面、音频、细块联动和移动尺寸性能见6.1节。
没有新增“手机全量已验”结论。

### 6.1 最新目录、入口及性能核验

三本 v3 均恢复原卡组树、释义摘要列表和卡片三栏；单一宿主最多挂载 90 行，
保留深链选中、搜索、单元、翻面、键盘和手机尺寸目录抽屉。目录摘要从当前字段生成；
原 catalog 仅作组织依据，不能用旧缓存覆盖当前释义。已有明确成员关系的说明卡单独入口；
没有旧目录的新学科默认保留全部卡，不能按无 Word 的旧 `kind=guide` 推断并隐藏数学卡。

- 总入口：`http://192.168.3.5:8771/study-catalog-20261015/index.html`；本机 `http://127.0.0.1:8876/`。
- 总入口按用户要求复用原完整书架：封面、进度、开始学习、继续上次、帮助及下载布局/行为保留，
  只替换三本“浏览全书”目标和本页帮助锚点。原根书架未改；8876转到同一LAN服务以复用既有进度。
  原书架静态书卡数量、学习服务和20261007下载仍保持原路径，不能据此声称已切换到PG新包或新评分服务。
  主线程本轮真实浏览器已观察三本动态进度、点击帮助仍在本页、从2027浏览链接进入v3三栏并返回；
  截图 `/tmp/study-catalog-old-bookshelf-20261015.png`。未评分或重置学习记录。
- v2 入口保留 SHA 备份后转入 v3，卡片、目录和查询参数保留。
- 三书所有正反面 payload、完整 catalog、媒体原字节及实体对应均保留；这不是修改 Anki 内容或学习记录。
- 当前默认展示例句合计为 2027 的 136,495、2026 的 137,057、刘晓艳的 20,178；
  来自实际原生正文及 lazy manifest，区别于过期目录缓存，不是重新计算或改变物理词频。
- 本机访问 LAN 地址的 IAB 样本：目录可点 539 ms、首张正文 585 ms、完整就绪 835 ms，部分缓存；
  不冒充真实手机冷启动。三书 LAN 目录、翻面、切卡、音频资源和键盘有实际记录。
- 8771 专属服务调度、并发接入与压缩已修；进度数据库重载前后 10 表摘要一致。
  9 个明确导出入口走受限静态映射，未开放整个 AppSupport，路径/祖先替换/并发回滚均有回归。

记录见 `output/study-catalog-20261015/shelf-qa.json`、
AppSupport 导出目录下 `web-directory-v3-qa.json`，以及
`data/web-study/service/static-mounts-20261015/README.md`。
独立复核已关闭本轮实际 diff 的 P1/P2；仍不能代替下方完整恢复结果。

### 6.2 连续切卡和背面逐段渲染：主body优化已应用，完整稳定性重新验收

上述首屏部分缓存样本不证明连续操作始终流畅。用户随后报告每次打开都逐段出现，
主线程在实际IAB复现objective翻面后先只有词头/音标，随后正文和词源才出现。
目录切卡强制重建90行与背面在正文前同步执行原FrontSide外链脚本分别核查，
不能将只减少目录重建称作背面卡顿全部解决。本轮修复包括：

- 切卡复用目录行；三本现有v3共用同一宿主，不再每次重建整份目录和外层卡片页面。
- 完整解析原正文、预取样式后一次提交head/body，再按原次序启动精确摘要批准的脚本。
  未使用隐藏正文等待“就绪”的遮挡方案；词源子页和细块媒体仍自然初始化，不承诺所有异步工作在首帧完成。
- 缓存最多4张卡、2MiB保留字符串预算；过期请求不能覆盖新卡，切换正文未提交时翻面按钮暂不可点。
  未知脚本、额外wrapper逻辑、noscript等解析差异保守使用原页面，保留源行为。
- `study_catalog_export._web` 在已有正反面生成遍历中收集脚本身份，所有后续书籍沿用同一factory；
  不只修改现有三份成品，也不为书名另设执行规则。

实际IAB五卡QA：objective、abide、train、2026 remote、刘晓艳ambition。
记录到的背面首个可见帧均已有释义和原生例句；四个定时样本为156.6、278.7、311.5和194.4ms，
这是混合缓存的本机样本，不是手机冷启动保证。abide两处展开保留原句/翻译/审核；
刘晓艳词源exit双语例句、韦氏音频readyState=4、空格翻面、方向键和快速连续导航已实点。
原子宿主17项回归及随后2项边界检查通过；独立复核关闭四项P2，并通过新增统一生成接线的3项定向检查。

曾复现专用8876验证服务队列5导致存在资源随机连接重置；仅此临时服务改队列128后，
24请求/12并发为18个存在资源200、6个预期404、连接异常0。未改8771/8765、代理或数据库。
三本正式LAN入口均实际翻背面并确认共享宿主，2027细块ready、词源高度完整，原文链接仍改写到LAN8765。
三份catalog摘要、cards/media链接和五张源卡wrapper/原文摘要不变，未写学习进度、原字段或APKG。
正式宿主不含QA测量代码。备份和摘要校验回滚脚本在
`exports/20261015/host-upgrades/shared-atomic-v1-575478cc5325/`。
实际结果与范围见 `web-atomic-runtime-qa-v1.json`、`web-shared-atomic-rollout-v1.json`；
截图 `/tmp/study-web-atomic-production-20261015.jpg`。本轮没有新增Safari或真实iPhone验收声明。

**用户后续验收未通过**：用户给出的实际地址仍是同一已推广新版，
`master-redbook2027-web-v3/index.html#card=6fe10daa961ab1f651f720e5ba4207420f92de491b7b1867655d59d56a16a102`（radical）。
因此前述首个可见主body样本不能证明整张卡已稳定。词源子文档仍可重复初始化，
AS细块和词典片段仍异步追加面板；该项保持未完成，继续以整张可见卡的重排/长任务和实际操作验收。

同一radical实际基线为 `radical-whole-card-baseline-v1.json`：首屏后记录5次布局变化，
词源高度从320变为1332像素，例句起点从1453移到2388像素。后续仅把词源初始化减至一次的候选
仍出现320→1→1332，不能称为解决；该失败记录另存 `radical-materialized-failed-layout-v1.json`。
只读核查确认1像素来自原子页临时测得body高度0后的原始回传，并非固定正确高度。
用户再次明确验收目标：点击显示答案后背面完整出现，不能先显示半页再补内容。
下一版采用当前卡正面期间准备完整背面的方向；必须实测整面提交后的稳定位置，
并复核审核展开、年份筛选、所有例句/物理计数、音频与键盘交互。后续结果见6.3节，失败记录保留。

### 6.3 整面准备后切换：实现及样例已验，全书推广中

当前统一factory在正面展示期间准备当前卡的完整背面。原HTML存储片段、审核证据和原生lazy例句
先做可逆展开，原JSON与物理位置摘要另行保留，继续由原模块验证、分组和安装交互。
真实子页面在最终宽度下完成字体、图片、布局和主题握手后，直接切换已经连接并测量的完整页面；
切换时不重建、搬移或重新导航词源iframe。仅保留当前展示和当前准备两面，无相邻整卡预载。
尺寸或字体变化使旧就绪状态失效，过期请求不能替换当前卡。原音频在最终基址和DOM连接后重新选源，
保留src/preload/媒体原字节，不自动播放。

实际IAB的radical整卡记录：词源只初始化一次；整面提交后词源1413像素、例句起点2469像素稳定，
4768.2像素正文没有后续几何变化。热准备完成后的单次翻面提交10.6ms；
这是本机单样本，不是手机或首次网络下载的时间保证。
六卡实际检查覆盖radical、objective、abide、train、2026 remote及刘晓艳ambition。
objective全部14条例句直接就绪；train原生例句1–43连续、物理次数45不变；
abide两处原句和完整审核可展开；刘晓艳原韦氏播放按钮实际成功，音频无错误。
原文/译文及词源可见文本另与保存的原页面逐项比较，objective补齐的是原lazy清单的11–14条，
不是新增释义或改写内容。UI展开、年份筛选、音频引起的正常交互变化不作为初始加载重排。

正式factory模式另验证preparedIndex与gzip交付、三书共享宿主、无QA采样，见
`factory-production-mode-ui-qa-v1.json`。29项集中网页/展开回归通过；独立review关闭本轮P1/P2。
普通LAN服务会改写部分公共JS的地址，因此精确脚本读取使用完整Range并严格检查范围、UTF8长度和原SHA，
不降低校验、不改服务或原媒体。实际LAN资源读取及新增回归通过。
最终源码安装报告为`wheel-current-install-qa-v6.json`：133个包文件和25个MathJax资源逐文件摘要一致，
新增展开模块/LAN模板实际安装、两CLI帮助从临时target运行成功。v4/v5仅为历史适用范围。

现有三书通过独立目录准备同一factory的交付资源；原cards、media、catalog及APKG不写入。
正式入口推广、原导航保留和LAN实际整面复核仍待下方终态记录；不以样例通过冒称全书已切换。

## 7. 完整恢复与独立对账：已完成

迁移前备份 `backups/study-catalog-20261015/catalog-20261015T011656-220779b4.pg.jsonl.gz`
是空库基线；它只能用于说明迁移前状态，不能证明当前数百万对象可完整恢复。
完整备份已生成于 `backups/study-catalog-complete-20261015/catalog-20261015T050938-13e19fdd.pg.jsonl.gz`，
实际7,131,700,562字节，文件SHA256为 `4d43782e8735d85b0fc9205df3f7ac3a3389f6131517226becf0a48b6cc5281d`；
全文件哈希期间大小、mtime和inode均未变化。已实际恢复到新schema
`study_restore_20261015_full_v1`，随后独立完整对账通过；终态报告为
`output/study-catalog-20261015/full-restore-verification-v1.json`，`complete=true`。
报告覆盖全部24张表、8,118,998行，逐行校验备份header、footer、行数与行流摘要，
再比较恢复库每张表的完整payload指纹与重复行数量；不是抽样或只数行。
恢复耗时23,661.99秒，之后完整对账793.60秒；日志24,455.59秒为两者累计。
此前COPY外键检查期间作业确实仍在进行；同一作业已自然完成，没有因观察超时重启。
独立审阅另以最小只读查询确认schema已提交、24表存在、未验证外键0、未完成来源0；
恢复验证模块与执行环境源码摘要一致。备份SHA封印沿用已保存全文件校验，未另扫7GB重做同一结论。
实际主库深校验已经终态0、`ok=true`、`problems=[]`，完整校验3,667,957个内容对象。
验证器另核对每个历史表的完整原始行流摘要、顺序连续性和归一化物理位置行数；
其范围见 `study_catalog_export.verify_catalog`，不是只抽查已展示卡片。
恢复流式指纹、二进制/浮点、重复行及失败回滚测试是前置证据，不替代实际完整库报告。
恢复对账中的序列范围是未来插入安全性；备份 v1 没有保存历史 sequence 高水位，不能扩大成历史序列状态完全还原。

完整恢复门槛已关闭。网页整面稳定性和其最终Git节点继续按6.2节单独验收，
不能用数据库恢复成功代替网页性能或手机实际体验。

## 8. 本地证据索引与SHA256

以下文件为本机实际生成证据；大型数据、卡包、机器日志和临时运行目录不提交Git。
此Markdown保留路径、摘要和已观察范围，不能把本地路径当作已发布下载链接。
报告改变或代码/输入/运行环境变动后，先核对相应范围是否仍有效再复用结论。

| 证据 | 实际本地路径（项目相对路径或绝对路径） | 文件SHA256 |
|---|---|---|
| 迁移与全表历史行 | `output/study-catalog-20261015/migration-v1.json` | `a2a1bf5a7a5b37b8cac68ebc245c636b0f61fb575b1ae8ae3ce471591ba77716` |
| 实际主库完整深校验 | `output/study-catalog-20261015/master-deep-verification-v1.json` | `9eb14be3e9d30919c4c24ec005d6609ff2f7a70d657e0a0a4e5c84b614019d41` |
| 三包全部ZIP成员 | `output/study-catalog-20261015/apkg-source-member-parity-v1.json` | `42eb08b6bfdbcc2a4c8fb46ca1f6c6740fccb265171601a4bec0eed635112e5d` |
| 刘晓艳原生完整包 | `output/study-catalog-20261015/liu-native-qa-v1.json` | `1ecef80c9d0c2812c505e1801d1c42aa31b844123507d48a6ac92231b9bf137a` |
| 2026原生完整包；旧措辞限定 | `output/study-catalog-20261015/redbook2026-native-qa-v2.json` | `c2049c9d9d7ee5478e4ff0821d5064b9d915b575764476305ccde77a1166476d` |
| 2027原生完整包；逐字段NFC计数 | `output/study-catalog-20261015/redbook2027-native-qa-v2.json` | `4e570b2e3c99eff19dca43886aee5046ed6e5e85c105ae39261fd151490d5511` |
| 数学构建样例 | `output/study-catalog-20261015/qa-math-build-v2.json` | `49787e09ea9293fdfe143d4abdbef7e1a405eb11d3277108540c36fba8470e0b` |
| 数学原生双模板样例 | `output/study-catalog-20261015/math-native-qa-v2.json` | `e1834fc44aba4f23251ec3e5f166307f310bbdf5d567e882a87dcec38e645bcb` |
| wheel数学资源安装 | `output/study-catalog-20261015/wheel-math-assets-qa-v1.json` | `02f626c620a0002c25827400cd3e580974f536f5f13e983b105acd7f6c3e4d85` |
| 当前源码仓库外安装 | `output/study-catalog-20261015/wheel-current-install-qa-v3.json` | `b1e43ee97fd25cca7cb4082140a616db0f394fdc845d75a174396ff62dbb924e` |
| 共享宿主后当前源码安装 | `output/study-catalog-20261015/wheel-current-install-qa-v4.json` | `c1292e21f35a79887f3f0175bf751d18d9ddf8309d7f6b081bf1d3567e51d26f` |
| 原子挂载实际浏览器 | `output/study-catalog-20261015/web-atomic-runtime-qa-v1.json` | `33e2a624aff811f3fd5b9148b1c11165707fdd1a2ccaf3956eb4fe6d0eb7ebfc` |
| 三本正式页推广和源保留 | `output/study-catalog-20261015/web-shared-atomic-rollout-v1.json` | `1396aee8d4dd6e751c7568e02ab44700b2daf8ff71b41729b5fd9b2ac203c60e` |
| 原版完整书架及实际点击 | `output/study-catalog-20261015/shelf-qa.json` | `9adca145b03bd18be0bf625b184abbe4798a1806c17464d5d07684d40ac77c22` |
| 原生note/model回退 | `output/study-catalog-20261015/native-note-model-reverts-v1.json` | `f4443cf922048ba39cda0b82a60ab67fb15d8b233f09ffb010246d2a9fb9cd73` |
| 原生运行时版本 | `output/study-catalog-20261015/native-runtime-revisions-v2.json` | `71747f3e9d6d24ebeba3bde8e1f540ee9cbd68f60ea95ba5637e3deff8fffe23` |
| 运行时依赖 | `output/study-catalog-20261015/native-runtime-dependencies-v2.json` | `207f8eefdfb2329f32af9b7dc311de08627e2129634d522b25c39925b0cbf58e` |
| 语义/运行时交叉原生导入 | `output/study-catalog-20261015/native-runtime-semantic-sequence-v1.json` | `18c436f6cb0f968eb12e4f249a916aeff3275f8032efe4a84e81d77acdeb16bc` |
| 25次平坦来源链增长 | `output/study-catalog-20261015/source-chain-growth-v1.json` | `edd9e7d6b1de02afe2c0ed7d9d2826c10ed8343b37b844df3a5ae5c20fe80d91` |
| 刘晓艳全网页静态对账 | `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-liuxiaoyan2027-web-v1.qa.json` | `e8db99cb5507b3fe5a79467cf4528c7a9cc8834d87a326f564ce00af2fc09c90` |
| 2026全网页静态对账 | `/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v1.qa.json` | `8be37272af263da84ef38157de46183c9426c6abe0ae4e6d2cbc4826d98a2e39` |
| 2027全网页静态对账 | `output/study-catalog-20261015/master-redbook2027-web-v1.qa.json` | `c62e2d0ac2f9a19c7258c2f8e053169839590ae60bd6be50722a73844d527e53` |

关键专项日志另位于 `/tmp`，不是持久发布附件：`study-catalog-flat-source-api-22-v1.log`、
`study-catalog-content-flat-final-v1.log`、`study-source-identity-green.log`、`study-native-groups-green.log`、
`study-native-groups-regression.log`、`study-native-model-note-revert-tests-final-20261015.log`、
`study-native-versions-runtime-final-tests-20261015.log` 及前述candidate/integration日志。
它们用于限定本次检查过程；最终可交付状态以主线程补入的集中证据和实际产物为准。
