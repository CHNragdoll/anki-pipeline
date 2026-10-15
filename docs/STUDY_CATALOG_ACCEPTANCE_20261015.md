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
先做可逆展开；折叠的完整历史原稿与detail保持原生按pin共享、按原入口展开，
不把同份原稿提前复制到每个折叠位置。原JSON与物理位置摘要另行保留，继续由原模块验证、分组和安装交互。
真实子页面在最终宽度下完成字体、图片、布局和主题握手后，直接切换已经连接并测量的完整页面；
切换时不重建、搬移或重新导航词源iframe。只保留当前卡正反两面，无相邻整卡DOM预载；
同卡反复翻面复用已就绪的DOM，换卡才清理旧面。
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
`factory-production-mode-ui-qa-v1.json`，历史修正后六卡重新由同一factory生成并逐项比对原历史markup。
32项集中网页/展开回归通过；独立review关闭本轮P1/P2，新增4项历史/嵌套detail回归独立通过。
普通LAN服务会改写部分公共JS的地址，因此精确脚本读取使用完整Range并严格检查范围、UTF8长度和原SHA，
不降低校验、不改服务或原媒体。实际LAN资源读取及新增回归通过。
此阶段源码安装报告为`wheel-current-install-qa-v7.json`：133个包文件和25个MathJax资源逐文件摘要一致，
新增展开模块/LAN模板实际安装、两CLI帮助从临时target运行成功。v4/v5/v6仅为历史适用范围。

现有三书通过独立目录准备同一factory的交付资源；原cards、media、catalog及APKG不写入。
第一次全量构建暴露了more的严重边界问题：17,177,302字节原wrapper含578个历史引用、仅4个不同pin，
逐处预填折叠审核使单卡JSON膨胀至2,327,361,440字节。已终止仅该隔离构建，失败记录保留。
修复后同一more为19,425,775字节JSON、2,417,684字节gzip；原578个pre markup逐项相等、4个pin完整保留。
真实8771 canonical mount中的整面背面一次包含全部626条例句，物理次数688；
实点4层原审核入口后读取1,366,844字符的完整原HTML证据，其SHA与原pin精确相同，见
`more-canonical-lan-ui-qa-v2.json`。此时没有全历史预填或QA采样；主动展开引起的正文增长属原交互。
全书隔离重建使用`host-upgrades/prepared-whole-v2/`，正式入口推广与逐书LAN复核继续单独记录。

全量只读检查另发现2026原生审核19个AF注册文件含localhost URL，普通代理改写会破坏原decoded pin。
服务只对严格的`_ac_/_as_/_af_`24位摘要注册文件及`_study_`64位摘要JS保留原字节，
不改path/mount/客户端/端口权限，普通脚本仍按原规则改写；42项组合测试及独立4项回归通过。
仅任务专属LAN代理按原参数、摘要备份与CAS流程重载；实际19文件复核和正式入口终态另补。

### 6.4 正式三书整面推广及切卡性能

全量准备最终覆盖15,174张卡，三书fallback均为0；原cards、media、catalog及APKG不写入。
正式三书已先按逐文件CAS推广整面资源，再推广同卡两面复用与有界预测宿主；
备份、前后入口摘要和回滚脚本分别保留在`host-upgrades/prepared-whole-rollout-v2/`及
`host-upgrades/prepared-smooth-v3/`，不把失败的2.3GB候选用于交付。

第一次最终冷刷新复核重新发现偶发回退，原失败记录保留，不能沿用此前成功样例遮盖。
子页错误精确指向原`min-oval.png`；它是合法457字节PNG。
只读并发实测显示loopback后端16次中3次连接失败，LAN对应出现502，非例句丢失或图片损坏。
后端原连接接收队列为5，改为128；代理只对尚未发送请求的GET/HEAD连接失败最多重连一次，POST不重放。
仅实际源字节与文件名摘要相符的静态资源使用private immutable缓存，普通脚本改写及API/Range规则保留。
重载保留原label、参数、监听、路由及权限，另保存源码CAS回滚和在线进度备份。
修复后两端各32请求/16并发与6图混合突发全部成功、原SHA一致，HEAD/304/206/gzip及原书架入口通过；
进度10表完整逻辑摘要未变，reader/QA/PG未动，见`lan-resource-burst-qa-v1.json`。

同卡两面复用、当前文档身份失效、跨卡清理、2MiB后台流式上限、前台接管和16MiB/4卡缓存均有回归。
独立review关闭超大预取与iframe导航后旧文档两个P2，部署器正常/并发index/并发COMPLETE三种隔离验证通过。
此前源码节点`08669f4`；该节点包安装报告为`wheel-current-install-qa-v8.json`，133文件逐一吻合。

实际LAN的三本正式入口分别检查2027 radical（9例句）、2026 remote（4例句）、刘晓艳ambition（23例句），
均为connected-complete-card，无QA逐帧采样，刘晓艳原韦氏按钮播放就绪且无媒体错误，
见`smooth-three-production-ui-v6.json`。共同宿主诊断样例连续切卡front37–45ms、back0.7–25ms；
五次刷新后立即翻面均未回退，front276–968ms、flip0.7–67ms，提交后几何只有初始一次变化。
这是本机IAB经真实LAN地址的结果，不是手机硬件或所有网络的时间保证。

随后同一共同宿主加入大文本SHA Worker（最多2个、8个任务、64MiB输入预算）、等价快速SHA核心、
并行读取/校验、精确wrapper边界解析、跳过注定超出缓存上限的stringify，以及自有Cigen几何合批。
缺少crypto.subtle的准备realm转用父校验器，已有原生实现不覆盖；原算法/BufferSource和错误语义保留。
原作者脚本字节与顺序不改，提前登记child/load/error，真实就绪后才提交；
实测更慢的tag间task让行候选已撤回，不把测试通过当成速度通过。
49项集中回归、定向独立复核与最终v10安装对账通过，见`async-sha-worker-qa-v8.json`及
`wheel-current-install-qa-v10.json`。后者133个文件精确吻合，包源封印为
`afc7505b69489185b3d69458aaedf94cd8224c6605390d0617860e9fb05e5f4b`。

本轮只替换三书共同host入口，逐文件CAS推广记录在`host-upgrades/prepared-smooth-v4/`；
原目录、导航配置、cards/media和全部prepared sidecars未变。三正式入口均再次实测完整就绪且无诊断采样，
见`smooth-three-production-ui-v7.json`。最终轻量QA连续三卡的front为462、72.8、36.2ms，
立即翻面为16.8、1、0.7ms，见`smooth-normal-cards-final-v8-ui.json`。

最大长卡more仍单列：626条例句、688次物理出现、578个原history pre齐全，native状态ready。
最新冷开测得front1917.1ms、立即点击背面等待2251.7ms，见`more-worker-v8-final-ui.json`；
先前同步候选曾有1324/1503ms，不能拿较快的旧样例替代最终这一轮观察。
当前仍继续定位长卡初始化代价，不能将普通卡的热样例速度扩大为全部卡首次打开均已秒开。

最终保留两个有实际依据的无损改动：原生投影先按精确文本和processed状态筛选，再只为命中根构造
原有完整view；全部匹配根仍先统一快照，process函数逐字不改，非HTML走原view。
未命中根的节点记录和码点偏移无需分配。894个唯一短文本实际约251KiB，
原256条预热缓存会顺序淘汰；提高为2048条但保留1MiB文本预算、单值门限和失败逐出。
两个原native pin及四处精确字节边界均受限核对，原始模块文件、全部侧车、字段和APKG不写入。
51项相关测试、两轮独立定向复核与v11安装通过；见`async-sha-worker-qa-v10.json`、
`wheel-current-install-qa-v11.json`。最终包源封印为
`04a6d7c34b245bd77c044da8a45e7e371b3f0b395777c3bbcb9f0a98d4d91a0d`。

正式host为`study-web-host.v8-indexed-projection`，CAS备份及回滚记录在`host-upgrades/prepared-smooth-v5/`。
三本正式入口再次验证了新适配、完整原文及无诊断采样，见`smooth-three-production-ui-v8.json`。
测试/构建任务停止后，最终普通卡连续切换为37.3/32.8ms、翻面1.1/9.6ms；初次radical为676.2ms，
见`smooth-normal-cards-final-v10-ui.json`。最终more从同书前一张切入为670.2ms，立即翻面仍1569.2ms；
新页直开为1887.8ms、立即翻面2591.4ms，见`more-cache-v10-actual-ui.json`。
626条例句、688物理次数、578历史引用及native ready已实核；不把旧版较快样例冒充本轮全部首次瞬开。
普通卡及书内选卡已达到亚秒，超长卡首次背面仍为明确未达全部瞬开的边界。

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
| 完整备份恢复与24表对账 | `output/study-catalog-20261015/full-restore-verification-v1.json` | `0d14c957c50ed079f0c73cc46b7082174d828b4cbce61d8ad07d506da889d793` |
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


### 6.5 2026-10-16 长卡热点与扫描优化

已核验的12e作者脚本保留全部6个IIFE和两次执行，仅把`[class]`扫描缩小为`[class*="_r"]`；资源原SHA和唯一源码边界仍先校验，其他脚本原样。实际more聚合中该IIFE从约100ms降到9ms。52项相关检查通过（66.082秒），独立审查无P1/P2；共同host更新至`study-web-host.v9-compact-author-scan`，三入口CAS备份在`host-upgrades/prepared-smooth-v6`。

`minimal-auto-compact-scan-actual-ui.json`使用仅记录提交时钟的QA壳，正面就绪后立即请求背面：本次more首次背面2.386秒，626条主例句、688次物理出现、578份原生历史引用、native ready均保留。相邻原基线为3.265秒；两次前台切入分别2.010秒与1.562秒，主机有其他活跃工作且本轮检查耗时较先前增长，不能把单次总耗时差当作稳定性能保证。最长卡首次等待仍未完成优化。

诊断候选只在独立QA页：延长owned布局hold、相等字体值保护、主例句CSS containment均未取得整体收益，未进入生成器或三个正式入口；折叠历史template隔离也未推广。完整数据、统计、源媒体、APKG、PostgreSQL与学习进度均未改。

证据：`output/study-catalog-20261015/compact-author-scan-qa-v1.json`、`function-profile-v1-actual-ui.json`、`function-profile-v6-alias-substring-actual-ui.json`和`minimal-auto-compact-scan-actual-ui.json`。先前v11安装包核验属于扫描优化前的source seal，本段不将其视为新源码安装验证。


### 6.6 独立脚本资源并发（2026-10-16）

公共`collectAuthoredScripts`先同步核对全部执行规则，再并行读每个独立、逐SHA验证的资源；数组位置和之后作者同步执行顺序保持不变，CSS仍原路径。实际more首次正面的6个真实cache-miss同时开始，各66–169ms，总脚本准备170ms；背面仅一个新增资源11ms，总准备12.8ms。不得把该局部阶段等同整张卡耗时。

53项相关检查全部通过（72.194秒），新增13合同覆盖并发、乱序完成、错误处理与拒绝规则；独立增量审查无P1/P2。v12干净安装验收133个文件逐SHA匹配，MathJax25+SOURCE、LAN模板、两CLI的真实target导入/help均通过。v12报告SHA`6433111f71b65662edfa76b602dddbf3f6eefdec88ab7d299b77c811ecc79d08`，source seal `d760512a6edaebf37a18f40ba0ef2c91d52cafa6317b167662b3c04f2e36f439`。共同host为`study-web-host.v10-parallel-verified-scripts`，三入口CAS备份在`host-upgrades/prepared-smooth-v7`。

同一仅记录提交时钟的QA，正面一完成即请求背面：more本次正面2.530秒、首次背面2.720秒，626主例句/688次数/578历史引用/native ready均保留。普通书内切卡实测36.7–253.7ms，立即背面228.1–540.9ms；普通整页首开正面1.163秒。当前主机负载及各轮网络/cache条件波动，记录实际值，不宣称长卡已全部首次秒开。下一步按`STUDY_WEB_FACE_DELIVERY_PLAN_20261016.md`拆分小正面交付，背面仍全校验和一次提交。

证据：`parallel-script-resources-actual-ui.json`、`parallel-verified-scripts-qa-v1.json`、`wheel-current-install-qa-v12.json`、`minimal-auto-parallel-script-actual-ui.json`、`minimal-auto-normal-v10-confirmed-ui.json`（均在`output/study-catalog-20261015/`）。

### 6.7 独立正面与完整背面预备（2026-10-16）

共同host升级为`study-web-host.v11-independent-fronts`。每个正面由root-pinned index里的独立SHA认证，绑定原card、wrapper/payload/front、完整artifact与module cohort；显示后完整wrapper和artifact继续原严格校验，再原位接入同一会话。翻面仍等原脚本、native、子文档、字体及几何完整就绪后一次显示。取消旧请求、立即翻面与A→B→A不会让旧包覆盖当前卡。旧协议仍兼容，缓存预算不变。

全量backfill覆盖2027红宝书6532、2026红宝书6682、刘晓艳1960，共15174张，无fallback。原full prepared规则和JSON/gzip字节、原wrapper及catalog保持不变，来源wrapper/payload指纹与此前逐书报告相同；未重扫全量媒体，沿用已有效的原媒体证据且本次不写媒体。数据库、APKG与学习记录未改。

| 书 | 独立正面字节 | gzip字节 | 新prepared index SHA256 |
|---|---:|---:|---|
| 2027红宝书 | 45,752,375 | 12,933,750 | `5a4252796266588a6dc30141931344420bc2d6460688f2f581589d98a09fd151` |
| 2026红宝书 | 46,782,363 | 13,235,187 | `63fafaaf7fd1bc92303854ae153c9b32b9cc93c73ddd99ecd01280a368b112ee` |
| 2027刘晓艳 | 46,505,958 | 9,125,659 | `cb8a2bede6838522e67cfa65561c27cd92b679fc476cdce172f8303d7f211c42` |

实际隔离QA：普通objective书内切换143ms，预备后翻面6.2ms；最大more书内切换57.8ms，预备后翻面27.8ms。整页初开more正面651.9–1332.5ms，首次立即翻背面仍3297.8ms；不同轮次负载/cache有差异，不宣称全部首次秒开。正式三入口均实点完整翻面：radical 9例、remote 4例、ambition 23例；正式more仍626主例句、688次数、578历史引用，native ready。没有把初始化中的部分背面显示出来。

69项相关检查中59通过、10项因未提供隔离PG连接跳过；本次不写PG。原host阻塞整wrapper时不能先显示正面的失败重现、新host26合同、frame13种错配/取消/ABA及混合LRU预算检查有记录，集中独立审查无P1/P2。v13安装133个包文件逐SHA匹配，MathJax25+SOURCE、LAN模板、真实target导入及两CLI通过；报告SHA `19df9752dbc15efeada306ce419f96760a22ca4534941ac5290b40bb14068463`，包源封印 `21c19f3541c5102a32289143945ddfadabe542fe44a639bb50f8fef488c6c255`。后续文档更新不改变这些包源码字节。

推广计划、前后快照、来源封印及条件回滚保留在本机`exports/20261015/host-upgrades/independent-front-v1`。准备命令最终exit1是全部15174张及plan/PREPARED落盘后的结束日志形参冲突，数据已完成；修复仅日志，保留旧script/plan/marker/log历史后重封，未重跑数据。`prepare-logging-recovery-v1.json`准确保留该事实。随后正式promote exit0，六个入口文件均写入且最终来源复核通过；源码节点`fbf77a8`。计划SHA `c7f64a71e4e53ce53bd9f0570d8e1d0a6960a451f1cb07255bd9e60f99fb7ec2`；回滚仅恢复本次实际替换且仍保持自身字节和文件身份的入口，保留并发编辑及新增内容寻址资源。未推送、合并或更新远端Release。

实际证据：`independent-front-checks-v1.json`、`independent-front-{auto,normal,within-book}-actual-ui-v1.json`、`independent-front-three-production-ui-v1.json`、`independent-front-largest-production-ui-v1.json`、`wheel-current-install-qa-v13.json`（在`output/study-catalog-20261015/`）；正式页截图`/tmp/study-web-production-v11-20261016.png`。本轮未做物理手机逐卡验收。下一项仅值得隔离评估完整获取与正面挂载并行，不能凭该候选承诺最大卡首次立即背面subsecond。

### 6.8 并行获取候选与首页统计实拍（2026-10-16）

只在隔离QA壳尝试将完整获取提前到正面挂载前，正式生成器和三入口未改。交错实测基线正面676.8–752.8ms、立即背面5849.5–6269.8ms，候选正面781.5–2589.6ms、背面3835.5–4152.9ms；页面与子文档visibility均为visible。主机同时存在高负载应用及系统任务，不能由单轮数据给出稳定提速百分比。候选让正面一次退回约2.6秒，故未采用，保留v11；记录在`front-overlap-isolated-actual-ui-v1.json`。这些数据说明首次长卡仍以秒计，不能继续用此前3.3秒作为固定上限。

首页另补5张当前正式页原始截图，位于`assets/screenshots/readme-20261016`：总词频及义项次数、2021年筛选、同段3处目标合并与双语chunk联动、training正确归属及完整原解释、原双语句子与转归审核记录。实际默认视口1280×720，未改尺寸、未合成或修图；原始JPEG共524340字节，逐图URL/card/操作/SHA见`capture-manifest.json`。这些是桌面网页实拍，不冒充手机Anki验收。README把10月15日段落的“总库迁移仍暂停”改成当前分支已完成，并保留旧发行附件各自版本边界。

### 6.9 原卡页无损gzip传输（2026-10-16）

三书15,174张原卡页全部准备成功，原1,974,259,756字节对应gzip副本339,043,363字节，无未知prepared卡。公共工厂和host统一支持`source-gzip.v1`，保留原source SHA、骨架/双面/base、prepared来源及完整就绪校验；取消、解压后2MiB邻卡预算和旧协议兼容不变。FRAME、原wrapper/full/front/preparedIndex/catalog、APKG、数据库、学习记录及媒体不改。源码检查点`49758dc`，集中独立复核无P1/P2，host15合同、工厂拒绝/幂等/旧产物不变回归通过；v14干净安装133文件与两CLI通过。

独立stage prepare自然exit0；补充安装后副本必须存在的窄guard，保留旧script/plan/PREPARED并仅重封对应SHA，未重做压缩。正式promote exit0，三书原index/COMPLETE共6文件已推广为`study-web-host.v12-source-wrapper-gzip`；root index/full/front描述与v11一致，host SHA `ee4c11e575274f9401f4adf086113113d4c53d2754067147da837f222e644cb4`。条件回滚及完整源/输出封印在`host-upgrades/source-wrapper-gzip-v1`。

隔离实际内容对照：more新旧均626主例句、688次，按data-ownership-history-id均570个不同ID/1144份显示副本，native ready；该明确DOM口径不与旧报告578历史引用混算。gzip缩小传输量，没有证据说明首次冷翻已秒开；最长卡实测仍有秒级波动。Safari只取得一次首正面计时，后续原生读取超时，不记为Safari验收通过。详见[本轮验证和限制](STUDY_SOURCE_WRAPPER_GZIP_20261016.md)及`output/study-catalog-20261015/wrapper-gzip-*.json`。

正式三入口已实际翻到完整背面：train45次/native ready、remote4条/native ready、ambition23条/27次；均从DOM确认同一新host SHA与`source-gzip.v1`，保持shared挂载且无fallback提示。保存逐书UI记录与正式统计截图；没有用隔离QA代替这一步。首页README的5张详细统计/筛年/chunk/转归/历史实拍继续保留，新增本轮网页传输结果及未达标限制说明。

### 6.10 就绪前减少整卡布局采样（2026-10-16）

源码节点`5a6e232`只将未就绪时的整卡snapshot改为不采样，原ready谓词、错误/取消/期限及三个连续稳定样本不变。八合同有旧版失败重现，相关30测试通过；v15安装133文件及两CLI通过。三书原六入口已推广v13，原prepared root/front/full/wrapper数据、音频、PG/APKG及学习记录未改；正式三书及more实际完整背面复核通过。原始证据、计数口径、部署封印和恢复信息见[词源启动诊断的后续记录](STUDY_CHILD_STARTUP_DIAGNOSTIC_20261016.md#后续验证与已采用的小改动)。

该改动减少不必要的布局工作，不代表首次长卡已秒开。移开/暂存关闭历史的不同隔离候选均未推广；单次短结果不稳定，不能用删内容或延后原native校验换取更短计时。Safari/物理手机全量性能仍未验收。


### 6.11 公共模块并发读取与 Safari 性能边界

源码 `4e81848` 将prepared module的严格资源读取提前至普通作者脚本的并发阶段，保持完整策略先验、SHA和原执行顺序。
新增16合同有旧版真实失败，相关31项测试通过；源码及部署独立审查无P1/P2。三书原入口已更新v14，正式三书完整背面复核通过，
原卡/媒体/root index、PG/APKG及学习记录未改。v16干净安装133文件与两真实CLI通过。

首页保留5张词频细节实拍，并同步v14状态。原生Safari第一次独立最长卡结果为正面7518ms、立即背面72913ms，内容626条/688次/native ready；
第二次阶段测量尚未成功读取，不宣称冷加载或Safari性能完成。确切证据与后续限定诊断见[模块并发及Safari记录](STUDY_CHILD_STARTUP_DIAGNOSTIC_20261016.md#v14公共模块读取并发与-safari-新线索)。

### 6.12 本地摘要回退与 v15 入口

源码 `5a630ff` 让本地SHA回退复用已有Worker快速核心，保持输入快照、全部算法和来源校验、Worker预算及完整就绪门槛。
44项相关检查通过，独立源码及部署复核无P1/P2；三本原六入口已CAS更新为 `study-web-host.v15-fast-local-sha`。
实际LAN HTTP核对三个HOST字节、原prepared root和source-gzip协议通过，卡片、媒体、PG/APKG和学习记录未改。

Node与JavaScriptCore独立摘要对照全部一致，但后者的大index计算仍有约2.5–3.0秒；不把计算基准当作UI性能。
原生Safari连接超时，尚无v15渲染/冷加载验收；前节v16安装记录对应之前的v14源码，未冒称此次新安装。
首页5张详细词频实拍继续保留并同步当前状态。首次全部秒开的目标仍未完成；部署封印、失败准备目录保留及证据边界见[本地SHA记录](STUDY_CHILD_STARTUP_DIAGNOSTIC_20261016.md#v15本地-sha-回退复用已有快速核心)。

### 6.13 完整公共模块压缩与缓存

源码 `bb857ab` 只对精确的evidence/full-SHA模块使用完整GET，使既有LAN gzip与immutable缓存生效；旧来源继续Range。
46新合同和旧范围拒绝检查通过，相关31项检查通过，集中源码及部署独立复核无P1/P2。
三书六入口已CAS更新v16；实际HTTP传输1.95MB模块的248KB gzip并验证解压原SHA。
正式三书完整背面核对通过：train43条/45次、remote4条/4次、ambition23条/27次；原root、卡片、媒体、PG/APKG及学习记录不改。

隔离候选资源阶段缩短，但最大卡整背面仍约3.4秒，不能宣称全部秒开；v15新内置浏览器及未采用WASM基准分别记载。
首页README同步v16并保留5张详细截图，Safari/手机性能门槛仍未完成。
具体封印、实际渲染范围及一个失败QA探针的证据边界见[完整模块GET记录](STUDY_CHILD_STARTUP_DIAGNOSTIC_20261016.md#v16完整模块-get-启用现有-gzip-与缓存)。

### 6.14 当前代码与资源的干净安装

`wheel-current-install-qa-v17.json`对应源码节点 `f02887e5ddef49021f8a434f521f41fe5a4474bd`，
源码→wheel→临时target的133个包文件SHA全部精确相等，MathJax25项+SOURCE及LAN模板完整，
实际target导入及 `anki-study`、`anki-pipeline --help` 均exit0，全部过程约11.18秒。
报告SHA `98c8960a8cce78191648ddc7b2c62125de95cf3851114988d40c1207dfaab012`，
源封印 `107512fabc96ecb5bdb305fa129758db8ac1347b3a94fc0cd5aad20f0b8d42b5`。

临时验收脚本原先固定了旧HOST值，133文件已核通过后在该旧断言停止；旧失败日志保留。
仅将临时断言改为干净源码和target实际HOST逐SHA比较后完成，产品源码、旧报告v16均未改。
该记录不访问PG、APKG、真实Anki、服务或浏览器；不替代长卡性能和手机验收。
后续纯文档更新不改变本轮已核的代码和资源；wheel整体字节与README元数据仍按此源码快照记录。
