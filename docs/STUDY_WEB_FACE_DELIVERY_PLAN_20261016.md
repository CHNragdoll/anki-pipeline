# 独立正面交付与完整背面预备

目标：点卡先完整显示正面，不再等十几MB背面资料全部读入；背面保持原严格校验、完整准备后一次显示。当前三书共同运行时为v20，最新内容与部署见文末；以下保留各阶段证据。最长卡首次翻面仍以秒计，目标未完成。

## 已确认原因

more原wrapper约16MB、prepared JSON约19MB，当前fetchCard等两者到齐才mount正面，而正面只有2,801 UTF-8字节。不要用缩减内容、删历史、宽松校验或逐段可见加载解决。

## 最小实现

1. `prepare_library`在同一次完整wrapper编译核验内，额外写小front artifact，包含原sides[0]精确字符串、prepared侧0及proof、相对base元数据、同一modules cohort。新prepared index的card项封存front文件SHA和card/source wrapper/payload/front哈希绑定。保持原始导出、整卡prepared和缺少front项的旧路径。
2. `HOST_RUNTIME`先核验现有config根pin下的新index，再核小front artifact的SHA和完整绑定；动态按当前wrapper URL解析相对base。正面提交后，后台继续原fetchCard/readAuthoredCard/preparedCard严格下载、骨架/双面/base/完整wrapper和sideproof核验。不得凭编译证书省掉背面的原始来源校验。
3. `PREPARED_FRAME_RUNTIME`新增显式front-only会话和完整包attachment。front-only不可填假背面/空proof；现有prepareView(0)及native/脚本/子文档/字体/完整布局门槛照旧。整包核验后只attach到同一current/token，不重新mount重建正面；然后后台getView(1)。翻面期间仍保持完整正面，到背面真正ready才promote。

## 必须守住

- index中新增小front字节SHA；大artifact SHA本身不认证未下载切片。来源绑定包含同card、同index快照、同wrapper/payload/front SHA、同base与modules。
- generation/token贯穿每个await，A→B→A旧任务/失败都不能复活；导航及时取消。当前整卡必要准备不受邻卡2MiB投机预算误伤。
- 小front/整包共用现有4卡/16MiB保守LRU；超大整包仍不缓存，无新增无界缓存。只有当前card的2个真实connected面。
- 任何front缺pin、bytes/hash/来源不同，或整包与已展示front不一致，均只在仍为当前token时走原wrapper fallback。过期结果不改当前UI。
- `.sf-ownership-history`含as-manifest必须原样初始化discover。此前history template/字体hold/CSS containment诊断候选均未推广，不混入本次实现。
- APKG、PostgreSQL、学习记录、源卡、原音频、例句/chunk/审核历史和物理计数不变；三本当前书与未来factory走同一实现。

## 验收与节点

先失败回归，再实现：新front错SHA/错card/错快照/base/modules、完整包不一致、取消及A→B→A、back未就绪不闪半面、源脚本原序、legacy无front回退、共用缓存预算。导出前后整卡文件/计数与既有prepared内容逐SHA核对。

先对独立QA导出验证普通卡和more，记录首次正面/立即背面/读正面后翻面、连续切卡及几何稳定性；626主例句、688物理次数、578历史引用必须保留。失败不覆盖正式入口。通过后CAS推广三入口，记录回滚、本地Git、更新安装验收。网站实测不能替代手机Anki验收；不发布远端或Release。

## 10月16日实现及隔离验证

生成器已为每张卡输出独立、带来源绑定的小正面；host先验证小正面，后台继续验证原完整wrapper与整卡artifact。frame用同一会话原位接入完整双面，不重建已显示的正面。立即翻面会等真实背面就绪，快速切词会取消旧会话。完整artifact字节和既有4卡/16MiB缓存、2MiB邻卡预取上限保留。

失败重现使用HEAD的原host并拦住完整wrapper：原host不能先显示完整正面，新host通过。相关测试执行69项：59通过，10项因未指定隔离PostgreSQL连接而跳过（本次不改数据库）；独立复核host26合同、frame13种错配/取消/ABA、生成器及混合缓存预算通过，无P1/P2。v13干净安装133文件逐SHA一致，两个CLI和MathJax资源通过。

真实局域网QA中，more从相邻卡切入正面57.8ms，读正面后完整翻背面27.8ms；普通objective切入143ms，预备后的翻面6.2ms。more的626主例句、688物理次数、578审核历史、native ready均保留。整页首开more正面实测651.9–1332.5ms，首次立即请求背面仍3297.8ms；后台预备使后续翻面迅速，不代表首次立即翻长卡已全部秒开。不同轮次主机负载/cache会影响结果。

原始计时及内容证据在`output/study-catalog-20261015/independent-front-{auto,normal,within-book}-actual-ui-v1.json`。

全量15,174张卡已补齐front artifact，原wrapper/payload指纹与旧报告逐书一致、fallback为0。三书原入口已推广为`study-web-host.v11-independent-fronts`；备份、来源封印、计划和条件回滚位于`host-upgrades/independent-front-v1`。准备阶段仅结束日志函数重名报错，全部数据及封印已完成；修复后保留旧日志/脚本/plan并重封，未重跑或覆盖front，随后promote退出0。详细记录见阶段验收6.7。

三正式入口实点翻面通过：2027 radical 9例、2026 remote 4例、刘晓艳 ambition 23例；正式more复核626主例句、688次数、578历史及native ready。完整背面仍一次显示，原目录和链接保留。最大卡首次立即翻背面的约3.3秒限制仍存在，不把这轮推广等同全部首次秒开。

## 后续原页传输优化

v11之后已增加公共原wrapper无损gzip，三书15,174张原页由1,974,259,756字节对应339,043,363字节副本；原source/full/front/prepared index和FRAME就绪门槛不变。已推广为v12，原三个入口实际完整翻面通过。该变化只确认传输缩小和内容完整，首次长卡仍有数秒及更高负载波动；3.3秒是前一轮观测，不是固定上限。完整来源、验证、恢复与Safari验收边界见[本轮记录](STUDY_SOURCE_WRAPPER_GZIP_20261016.md)。

## v18：初始化期间暂存静态审核节点（已推广，首次秒开仍未完成）

本项仍以完整背面在显示前全部就绪为目标，不把审核内容改为点击后补载。
以下方案已完成隔离验证并接入共同源码，当时三本正式原入口推广为`study-web-host.v18-static-history-init`；后续v19继续保留该流程。

1. 仅对明确审计过的作者／native脚本组合评估完全关闭的静态审核详情。
   先按原流程解码完整DOM；保留details、summary及原childNode顺序，把符合严格条件的原正文节点暂存在Fragment。
   活动义项、例句、待核对区、原生物理索引行、lazy清单及初始化控件均不能暂存；未知组合维持原流程。
   不能把整个关闭history任意移走：原group会读取其中的native li，discover也需要首次登记as-manifest。
2. 不更改任何原作者执行顺序、原native算法或校验。暂存范围必须证明原生索引／discover贡献为零，
   且原fine、projection、bank本来排除该区域；其余作者初始化对这些节点也无必需副作用。
   位于example-card内的历史、含active chunk、活动SF行／年份控件、已打开的内层详情等均排除。
3. 仅在实际有暂存内容时等待native ready；失败及child error交回原门禁裁定，取消仍拒绝提交。
   native等待与后续原完整就绪检查共享原10秒期限，不能串成两个10秒窗口。
   native就绪后同步放回全部原节点并移除自有锚点，再通过原字体、词源子页及三次稳定几何检查；
   背面提交时不能留下任何待恢复正文，取消／异常清理不能触碰另一owner或后来复用的realm。
4. 先用生命周期与负例合同证明节点身份、顺序、空白／注释、summary与内容完整恢复，
   再对同一more实际比较完整正文、626主例句、688物理次数、审核记录、查找／展开／chunk与连续切换。
   只有实际提速且保真通过才考虑接入共同factory、集中独立审查及条件推广；不重写PG、APKG或媒体。

这个原型不减少首次DOMParser的解析量或节点内存；只评估后续连接树扫描与布局的成本。
若收益不足或发现内容差异，保留证据并撤回候选，不能用较小的测试范围代替完整目标。

### 已完成的定向验证

独立复核发现并修复两项P2：启动ID／发音控件可能被暂存隐藏，以及共享期限起点早于原media.load／refresh。
资格规则现拒绝root、summary和全部正文中的任何ID及启动控件，保留未知脚本组合的原路径；计时从原wait调用处开始。
真实固定版本作者的两组反例已先失败再通过，19项生命周期／完整恢复合同及101个资格负例通过；复核确认问题关闭。

修正版两本more实际验证：2027首次正面1694ms、立即完整背面2228ms；2026分别1411ms、2188ms。
两本均暂存570处并在最终门禁前全部恢复，未留待补正文；626条主例句、688次物理出现、1716个完整历史节点摘要多重集、
1144项历史ID引用、可见全文摘要与168151.3px整页高度均与各自正式v17基线相等，native ready且错误为0。
2026实际筛选2021年后16次物理出现合并为14条原文，总词频仍688；恢复后的5687元素审核记录可直接展开。

本轮2027正式逻辑对照为2973／3583ms，旧资格候选为1931／2258ms；修正后数据如上。
这是不同轮次的局域网观测，缓存与主机内存压力不恒定，不能据此承诺固定提速比例、首次全部秒开或Safari验收。
原始结果保留在`output/study-catalog-20261015/static-history-{fixed-2027,fixed-2026}-actual-ui-v1.json`、
对应`-content-v1.json`与2026的`-interaction-v1.json`。

共同源码仅将已核验候选的私有标识符改为生产命名，独立逆向改名后整份frame摘要仍精确为
`db9a56f73e7630091b3bb5a269dfc7ff1e375620da924093ba72c996c5c39b99`。
生产frame摘要为`a9671e7a6a1c02c0f03ddd8636578de2cc35fd3b7831e937161701dbeff879ff`，
runtime摘要为`db9ad02235855a1eeb50f71315b291a8424c507b751dd51da791ca2f72b4513d`。
4项源码定向回归通过（包含13个行为合同、90多个资格负例及原shell／FrontSession回归），独立实际diff复核无新P1/P2。
这些检查不代替后续正式入口切换后的实际UI、干净安装和Safari性能结果。

### 正式入口与干净安装

源码提交`0bab7e6`；外部源码封印后，准备和推广均自然exit0，仅条件替换三个原入口的index／COMPLETE共六个文件，
HOST资产、prepared root、原卡、媒体、PG、APKG和学习记录不改。stage为`host-upgrades/static-history-init-v1`；
脚本SHA `df0377485fc5d8fe48d0bac080ced6ebd77a8fa350dc3fb9d7017018406f0bd1`，
plan SHA `ebc6a009aa8d08cd5b65832677c6d1a652b4392a2d18ca5451b94ca1249f6ae7`。
六项部署合同及独立复核通过，保留既有HOST的最终摘要／stat重核和有所有权条件的回滚。

三书实际LAN HTTP config与本地一致，正式UI分别核对train43条／45次、remote4条／4次、ambition23条／27次。
正式more保留626条／688次、578个历史引用、native ready及一个词源子页，整份历史节点摘要多重集、ID引用、
可见全文和整页高度继续与v17基线精确相等；入口均为shared，无fallback。证据为
`static-history-production-http-v1.json`、`static-history-production-ui-v1.json`及实拍`static-history-production-train-v1.jpg`。

同一源码的`wheel-current-install-qa-v19.json`以13.39秒完成独立干净构建／仓库外安装，133个包文件逐SHA相等，
MathJax25项+SOURCE／LAN、实际target导入及两个CLI通过；报告SHA
`6a1be5ee24744c58378de9ad18049e7833ad7c4755a20cdeff7eb516f55e0464`。
这个v19是安装报告编号，网页运行时为v18；纯文档后续提交不改变该源码／资源核验范围。
该次仍无v18原生Safari性能结果，不能宣称首次全部秒开或把本节点标成整个目标完成。

## v19：完整就绪成员缓存（已推广）

公共源码 `12aea81` 在一次完整wait生命周期内缓存iframe/native成员；MutationObserver和读取前takeRecords负责失效，
无observer或异常时退回原查询，所有完成/取消/失败路径释放。源校验、child/native/fonts和三次稳定布局保持。
33项定向测试、实际长卡8项内容对照及独立审查通过；只确认减少查询/检查工作，不宣称整卡稳定秒开。

三书六入口条件推广、11项部署合同、实际正式more全文/688次、remote/ambition翻面与v20干净安装均通过。
HOST保持 `99e5b643…dc4ae7`，FRAME为 `d7e60fcc…1b59a`，FRAME HTML为 `5aa80ca0…9533a1`。
阶段报告、源码/入口封印、完整摘要及有条件回滚详见[成员缓存记录](STUDY_GATE_MEMBERS_CACHE_20261016.md#正式三书与安装)。
词源首次配置提前重发的方向已经过当前时序诊断，不能解决主要等待且存在ready去重冲突，不继续造候选。
首次长卡与当前Safari/手机性能仍未达到完成门槛。

## v20：翻面失败的终止处理（已推广）

共同源码`8ce86a7`修复末次就绪失效后静默false和异步rAF错误留下pending Promise两处控制流，
旧版回归先复现失败，修复后6项定向检查通过，独立复核无剩余P1/P2。
原来源、native、child、字体和三次稳定几何检查继续保留；旧请求不能解锁新请求。
三QA和三正式入口的正常完整翻面通过，正式条件部署只写三index／三COMPLETE，源数据和公共HOST不变。
干净安装报告为v21，133包文件、公式资源、LAN模板和两个CLI通过。
详细源码、部署封印和实际UI证据见[终止处理记录](STUDY_WEB_TERMINAL_FAILURE_20261016.md)。
这次可靠性修复不能证明Safari现场根因或稳定秒开；性能总目标仍未完成。
