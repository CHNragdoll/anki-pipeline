# 2026-10-16 长卡词源子文档启动对照

初始诊断从 `study-web-host.v12-source-wrapper-gzip`、代码检查点 `7603378` 开始，先只写隔离诊断页，没有替换正式产物。随后采用的布局采样、模块读取并发、本地校验及压缩请求优化、v13至v16实际推广分别单列在末节；卡片、数据库或APKG未修改。首次立即翻长卡的性能目标仍未完成。

## 已观察到什么

使用同一张 `more` 卡和同一份词源源码，SHA-256 为 `286dc79ad65112414ae691445c0b0e1e37ca00d929a9314b46e259bf0a54632e`。探针位于子文档 `<head>` 最开头，在原 CSS 和三个原脚本之前；同时记录子文档自己的 `performance.timeOrigin` 和首探针时间，避免把父页面收到消息的时间误当成子脚本执行时间。

| 隔离对照 | 正面 / ms | 立即请求背面 / ms | 子 timeOrigin 至首脚本 / ms |
|---|---:|---:|---:|
| 正式渲染逻辑，加父页面 50ms 心跳 | 805.6 | 5,858.2 | 3,190.5 |
| 在最终 document 新建 iframe，再连接同一完整 body | 843.1 | 8,604.2 | 5,891.5 |
| 准备页面置于可见顶层，仅用于诊断 | 613.3 | 5,309.5 | 3,064.9 |
| 同一原词源独立 srcdoc，无整张卡片 | — | — | 189.7 |

这些是不同轮次的单次记录，主机负载和缓存不受控，不能据此估计固定耗时或提升百分比。新建 iframe 和可见顶层两项均没有消除额外等待，不进入正式实现；可见顶层诊断会暴露准备过程，尤其不能用于交付。

第一项中，背面请求后 1,880.3–3,139.2ms 的父心跳间隔为 1,258.9ms；之后心跳恢复，子首脚本到约 5,335.4ms 才执行。因此“父线程始终阻塞到子脚本开始”不能解释全部间隔。首探针之后的词源 CSS、原 viewer 脚本、字体、图片或 ready 检查，也不能解释首探针之前的等待。浏览器导航/脚本环境调度和测试环境的影响仍需区分，尚未确认根因，不能断言 opaque sandbox 必然启动了新进程。

此前 offscreen/层叠/child 固定定位、可见浏览器、data URL 和减少未就绪布局采样等隔离候选也未得到稳定收益，均未推广。Blob 对照没有完成原协议就绪，不能作为性能结果。

## 当前 DOM 的成本分布

对子代理读取的同一份完整 prepared 背面做一次本地解析：body 共 89,994 个元素、53,652 个 span。关闭历史的最大子树合计 50,434 个元素，占总元素 56.0%；其中 24,396 个 span 全是双语 `card-chunk`。全卡 70.0% 的 span 位于关闭的 details 内。meaning-section 的 68,272 个元素与 examples-section 的 21,685 个元素已包含这些历史，不能再与历史数相加。

570 个 authority pre 虽有 7,151,288 字节文本，但每个只有一个文本节点、没有元素子节点；包括其 details/summary 也仅 1,710 个元素。其成本首先是原文体积，不能称为七 MB 的大量 HTML 节点。

这份分布提示后续应评估关闭历史的接入成本，但尚未证明它造成子文档启动等待。不能直接把历史移入 template 后宣称无损：现有 native 的 manifest/slot、投影、分组和年份筛选都依赖相应节点的初始化与连接。若改变这一阶段，必须先补齐延后接入和取消/恢复协议，再验证展开后的原文、chunk、审核与计数；当前没有应用这种变化。

## Safari 与证据范围

本轮 Safari 在取得当前窗口状态时返回 `AXError.cannotComplete`，未能开始该轮页面操作，不将内置浏览器结果算作 Safari 验收。没有使用其他自动化方式绕过当前窗口状态要求。

原始记录保存在本地 `output/study-catalog-20261015/`：`parent-pulse-ui-v1.json`、`child-minimal-srcdoc-ui-v1.json`、`child-owner-document-ui-v1.json` 和 `stage-visible-ui-v1.json`。`child-startup-diagnostic-summary-v1.json` 封存每份报告的 SHA、相对阶段时间和心跳间隔。原始卡片与词源源文件仍保留；完整性、原生和布局就绪门槛没有降低。

README 的五张真题词频实拍及捕获清单已在 `454d763` 提交，后续 v12 传输交付及已知限制在 `7603378` 更新。本轮诊断不改变这些截图对应的内容或计数。

## 后续验证与已采用的小改动

移开关闭历史内容的第一轮诊断中，子 timeOrigin 至首脚本约7.3ms、背面2,238.2ms；同一诊断复测却为2,212.3ms、3,842.4ms。精确原节点暂存、HTML文本暂存以及较晚移开历史也仍有数秒等待。因此不能把第一次短结果当成可重复的主因证明。这些只存在于隔离页，均未交付；正式页面没有删历史或加入暂存逻辑。独立复核还指出这类变换必须保留原manifest验证、解码、动态新slot发现和年份筛选的初始化顺序，不能只凭native ready字段放行。

更早的第一条语句探针也已补测：子首语句距timeOrigin1,913.7ms，原installed探针只晚0.4ms；首探针等待不来自就绪监听安装本身。原始记录为`child-first-statement-ui-v1.json`。

正式采用的仅是一处独立资源优化：`waitPrepared`原ready谓词为false时不调用整卡`snapshot`；仍逐帧检查原生状态、词源错误/签名/宽度、字体、取消及10秒期限。ready成立后仍需要连续三个相同的完整布局样本；中途重新未就绪会清空稳定样本。先记录旧逻辑的失败重现，再通过八项合同检查；连同materialize/front相关共30项测试通过，独立复核无P1/P2，源码节点`5a6e232`。

隔离实际页面中，新逻辑就绪门阶段只测三次完整布局（约17.3ms），完整more仍626主例句、688次、570个不同历史ID/1,144份显示副本及native ready。补测旧逻辑一次为六次、约39.0ms。两次不在同一负载条件，首次背面分别4,670.5ms和2,574.2ms，不能据此宣称新逻辑冷翻更快；结论仅为减少尚未就绪时的重复布局工作。另一次旧逻辑未在期限内完成而回退，原失败记录保留。证据为`ready-layout-{baseline,candidate}-ui-v1.json`及`ready-layout-baseline-ui-v2.json`。

三书六个index/COMPLETE入口已以CAS推广为`study-web-host.v13-ready-layout-gate`，promote自然退出0；新FRAME SHA `02b1f66d935a5436e520873e727031a0f8bdd17970a1734460d829255fe21b84`，frame HTML SHA `dd87af14eceed95f173fb51fee3630c29c683c47355a6e22720788f8f7ae26dd`。公共HOST SHA仍为v12的`ee4c11e575274f9401f4adf086113113d4c53d2754067147da837f222e644cb4`，root prepared index、front/full/wrapper报告与源卡/媒体不变。原数据证据沿用，没有重扫全库或媒体；PG/APKG及学习记录未写。

推广stage为本机`host-upgrades/ready-layout-gate-v1`，脚本SHA `37bcb1b5fc73e7156c94777aeb555fd43a5baf5b8dbd76112ac961bbe056da5f`，plan SHA `911de23da79d3232a170c8357089344db1121c3411d0c52c96d0bcef6780dc24`。保留六份前后快照及条件回滚，回滚不依赖后续产品源码仍保持旧版本；对应两项窄合同通过。新部署脚本独立复核无剩余P1/P2。

正式页面实际复核：train45次/native ready，remote4条/native ready，ambition23条/27次（该卡原本无native payload）；more626条/688次、570个不同历史ID/1,144份副本、native ready且无暂存候选节点。三书均确认新gate表达式、原root pin与`source-gzip.v1`。train直接例句43条，包含嵌套历史的`.examples-section .example-card`为44；旧报告使用后一个选择器，不能把这两个DOM口径混成内容变化。记录为`ready-layout-production-{2027,2026,liu,more}-ui-v1.json`，正式页面实拍`ready-layout-production-proof.jpg`。

v15干净安装133个包文件逐SHA一致，MathJax25+SOURCE、LAN模板与两真实target CLI通过。报告SHA `44a5c31c56a1060e9d0f6fd9457172d90c55b2fdd4ece54a4d6c3f59fa20477b`，源封印 `26b662b155ad8c32be11086cb580cd622c57d4408d50e8f9a65a9fbd3d87a33e`。安装与网页测试均不替代Safari/手机全量验收；首次全部秒开的目标仍未完成。

验收中另确认旧LAN代理PID61596及原exec句柄已不存在，后端PID61223/reader44199仍正常；按原argv恢复代理为PID993，仅监听原192.168.3.5:8771/8765，未改网络、端口或权限。后续正式网页验证均经恢复后的LAN地址。旧失败标签页留有浏览器生成的网络错误页，不以它代表服务仍离线。


## v14：公共模块读取并发与 Safari 新线索

源码节点 `4e81848` 仅把 prepared module 的资源读取并入已经通过全部策略校验后的 `Promise.all`。
源作者脚本规则仍完整检查完才请求任何资源；原 module 执行位置与源序保持不变，仍复用严格 URL|SHA 缓存。
预读不执行代码，也不把 native module 交给普通作者代码适配器。未更改释义、例句、chunk、审核历史、计数、媒体、PG或APKG。

实际旧源码红测后，新增16合同绿测；连同ready-layout/materialize/front共31项通过（53.157秒）。
既有script-preparation夹具仅更新了原先“native不预取”的过时预期，保留其余13合同。
独立源码及部署脚本审查无P1/P2。v16干净wheel安装133文件逐SHA一致、MathJax25+SOURCE及LAN模板完整，两真实target CLI通过。
报告 `wheel-current-install-qa-v16.json` SHA `bd440404bd6e3e9db0a88e70b080700530c9372cb0d65e1b7104a9fe02d5e4ac`，
source seal `0094470ad1b2ea49c4a9d88548ed00dc69ac400fdf213b349d0915128fc13d96`。

三书原六入口已CAS推广为 `study-web-host.v14-module-prefetch`，准备及推广命令均自然退出0。
stage `host-upgrades/module-prefetch-v1`；script SHA `20ed446883e79d5cbd7d7eaa4ab29057d5066b161870f214d53e379c9f6409d8`，
plan SHA `67ae31381064b6fa9bb29cb49943bf7d6fd861e32f67772827f246ce8e286ec1`。
FRAME SHA `a019f743cba5978d3bb3d8b5fd600e68642bddb5120d82e8d287a59a9feff776`，
frame HTML SHA `8ac1406bc249e17de90d9b96cdf9f453da3302190cd8946e93d17afbe783c41c`。
HOST、root prepared index和原front/full/wrapper报告保持原值；保留所有前后快照及条件回滚，不要求回滚时产品源码仍为该版本。

正式三书实点完整背面：train45次/43直接例句/native ready；remote4条/native ready；ambition23条/27次、原本无native payload。
三书均从实际加载config确认模块并发、v13布局gate、原root pin和source-gzip.v1。记录 `module-prefetch-production-{2027,2026,liu}-ui-v1.json`，
正式词频页原始实拍 `module-prefetch-production-proof.jpg`，均在 `output/study-catalog-20261015/`。

### 仍未达成的性能及接下来的限定诊断

同一more隔离页中，旧版本次模块读取校验83.6ms、执行15.2ms，模块直到realm-ready才开始读；
新版确认模块在普通作者脚本读取时已开始，realm-ready后无需新读取。该证据只证明去掉串行读取依赖。
新旧整页及长卡时长随负载/cache波动，不据此宣称总速度提升：旧背面3572.4ms，新版一次8314.2ms（与测试进程时间重合），测试结束后另一次5268.3ms。
原始记录为 `module-prefetch-{baseline-ui-v1,candidate-ui-v1,candidate-ui-v2}.json`。
逐作者执行的独立诊断 `author-execution-cost-ui-v1.json` 保留了重复pin的各次源序时间；首次编号refresh约147.3ms，第二次约0.2ms，未据此修改原编号或初始化语义。

原生Safari真实独立测量页最终完成，AX显示正面7518ms、立即完整背面72913ms，仍626直接例句/688物理次数/native ready/1词源子框。
记录 `module-prefetch-safari-result-v1.json` 明确是AX结果的人工数值摘录，不是自动导出的完整trace，也不是稳定统计。
启动后才Raise窗口，这一轮不能外推为用户前台环境的固定耗时。
第二次精确分阶段URL已收到HTTP200，但原生AX在后续读取超时，尚无该次阶段结论；另一次地址栏曾出现历史QA URL，
其旧trace不与当前v14结果混用。由此首次全部秒开的目标仍未完成，Safari不能标成验收通过。
下一步只定位Safari HTTP源校验的worker/回退路径，并用小SHA诊断区分主线程回退、计算和后台调度；不降低SHA校验、不删内容。


已准备独立SHA诊断页 `_qa-safari-sha-path-v1-20261016.html`，仅原样加载shim（SHA `6b3530d686233571669651aafba2eabca75bbe67bb755950eca198b3a2c74eff`），
顺序读取并核验原4.4MB prepared index与1.95MB module。记录Worker构造/传输/回复/错误/终止、摘要时长和主线程心跳，
不载卡片、不改生产算法；本轮仅确认脚本语法，尚未取得该页的Safari实际结果。
源码只读审查发现：任一Worker错误或10秒超时会永久禁用本页Worker，之后走慢主线程core，但现有结果不足以证明Safari已触发这条路径。
原生交互随后超时并重置连接，新的browser编号3已对应Chrome而非先前内置浏览器，不继续用旧tab编号操作其他页面，也未关闭用户Chrome标签。

## v15：本地 SHA 回退复用已有快速核心

源码节点 `5a630ff` 只把 `localDigest` 从保守核心切换到已有的 `fastSha256`，与Worker共用同一实现。
输入仍在异步前复制，算法与BufferSource拒绝规则、跨realm/DataView/偏移处理、原生SubtleCrypto保护、
Worker队列、64MiB预算及10秒期限均不变。Worker失败后的连续调用新增12种填充边界、偏移和调用后改写对照。
44项摘要、正面、挂载、布局及模块并发检查通过（77.925秒）；独立增量审查无P1/P2。

直接算法基准使用同一份真实4,435,220字节index与1,949,068字节module，所有摘要与原生结果逐字相等。
Node隔离VM中index由约249–1845ms降为49–83ms；JavaScriptCore C API的独立调用中，
index旧核心约5.4–6.6秒，快速核心仍约2.5–3.0秒，module快速核心仍约1.5–1.7秒。
这些仅测计算，不含页面加载，也不是Safari的Worker、JIT或前台行为证明；不能据此宣称秒开。
报告为 `local-sha-core-compare-v1.json` 与 `local-sha-jsc-compare-v1.json`。

三书原六入口已推广为 `study-web-host.v15-fast-local-sha`，原prepared root、full/front/wrapper、
音频、PG/APKG及学习记录不改。公共HOST SHA `26deb38071b5bc20229ea05fc9935080c8b75f13588d919f03d2d762eb61d407`，
LAN模板SHA `ea3c80d4b145e8cf1673cbf9be0af7249497f0d98c75cb0d48f896da16e109e6`，
frame HTML SHA `4ec4681dca66dfe7d72a5d6a17fd14f1cc3dfac77d8ca6fd169e47fda62eee9b`；
独立frame运行逻辑的SHA仍为v14的 `a019f743cba5978d3bb3d8b5fd600e68642bddb5120d82e8d287a59a9feff776`。

实际HTTP逐书核对新HOST字节及原root绑定，报告 `fast-local-sha-production-http-v1.json`。
LAN代理原本会在shell注入旧摘要/链接兼容脚本并改写回环URL，因此index按既有变换核验，
不把HTTP壳与磁盘字节不同直接报成数据损坏；真正加载的新内容寻址HOST逐SHA一致。
本轮原生Safari交互及新诊断页连接超时，未取得v15实际渲染/性能结果，v14截图和安装记录仍按各自版本保留。

部署stage为 `host-upgrades/fast-local-sha-v2`，脚本SHA `22b04fbd9da17595d0cef3d2bbfe817cc3363a23b8313cf1a89bb76d2e1d6c4d`，
plan SHA `80c5769949a1cd08ab6c8e2de2564a29eb59268b781848b725aeb3cfbe4e3b8d`。
首次v1准备因frame HTML内也嵌有LAN模板而停止，尚未写正式入口，失败目录保留。
v2核对HOST前缀及HOST/frame里的同一精确逆变换，再以原CAS与条件回滚推广；准备和推广均自然退出0。
回滚仅恢复本次仍保持原文件身份和字节的六个入口，保留新增内容寻址资源及并发编辑。
当时另在隔离评估更快的离线摘要候选，未进入生成器或正式页面；后续排除结论见下节。

### v15 后续实际页面与候选排除

内置浏览器连接随后恢复。本轮正式train页面确实加载上述v15 HOST，完整背面仍为43条主例句、45次物理出现、
native ready及1个词源子框；`fast-local-sha-production-rendered-v1.json`与`fast-local-sha-production-proof.jpg`保存实际记录。
同一v15低扰动独立冷加载页测得最大more正面604ms、立即完整背面3808ms，626条主例句/688次/native ready均保留。
报告 `fast-local-sha-cold-actual-ui-v1.json`；这是本机单次内置浏览器样本，不能与v14 Safari的73秒直接算提速比例。
阶段记录中，SHA后正文解析约241ms、脚本资源约680ms、作者循环及批量布局约715ms、完整就绪等待约887ms，
仍需分开定位，首次全部秒开的目标尚未完成。

WASM只做隔离原型，未纳入源码、安装包或正式入口。官方hash-wasm 4.12.0归档完整性及嵌入binary均核对，
24项摘要/快照/边界合同、Node和独立JSC原生对照通过；原型、MIT与ISC双许可保留在本机临时目录。
实际内置浏览器对同一真实输入交错比较：4.4MB index的快速JS约21–45ms，WASM约17–49ms，加首次初始化约42ms；
module约9–27ms与6–8ms，全部摘要与封存pin相等。该收益不足以据此引入新依赖，候选未采用。
报告 `wasm-sha-prototype-v1.json`、`wasm-sha-comparison-actual-ui-v1.json`，均不替代整卡或Safari验收。

## v16：完整模块 GET 启用现有 gzip 与缓存

源码节点 `bb857ab` 仅修改 `resource` 的请求方式：解析后pathname必须精确以
`/evidence/_study_prepared_module_<当前64位小写SHA>.js` 结尾才使用完整GET，
其余旧资源继续Range，以保留代理不改写原字节的既有路径。完整URL/query不重拼，URL|pin缓存、失败清理、
24项限额、200摘要、206完整范围/UTF8长度验证及原执行/就绪规则均不变。
原版4种精确模块请求红测，修改后46项新合同与原范围拒绝合同全过；相关31项检查通过（41.050秒），
源码和部署集中独立复核无P1/P2。

隔离实际页中资源阶段由一次基线约680ms降为261ms，但整背面仍需3365ms，626例句/688次/native ready保持。
基线和候选非同时运行，不能把单次整卡差额当稳定提速；候选额外使用no-store排除客户端模块缓存，
正式版则允许现有不可变缓存。报告 `content-address-get-isolated-actual-ui-v1.json`。

三书原六入口已推广为 `study-web-host.v16-module-gzip-cache`。实际LAN普通GET读取该1,949,068字节module，
传输248,026字节gzip，解压原SHA精确一致，返回原有 `private, max-age=31536000, immutable`。
公共HOST仍为 `26deb38071b5bc20229ea05fc9935080c8b75f13588d919f03d2d762eb61d407`；
FRAME SHA `0641212f1aea10dd35392bc23f7e2565e21fb819fb3ffb18d1ee9b7179b45ee9`，
frame HTML SHA `c2f98f484a41a705eb1a2259e5aff3b339db29983af4daeb5fb72d5d9c00e889`。
原prepared root/full/front/wrapper、卡片、音频、PG/APKG和学习记录未改，也未重跑全量媒体。

正式三书实际背面：train为43主例句/45次/native ready；remote为4条/4次/native ready；
ambition为23条/27次，其原卡无native审核payload，不伪造一个ready状态。各1个词源子框，
DOM config均确认新精确GET规则及原root。实际记录为 `module-get-production-http-v1.json`、
`module-get-three-production-rendered-v1.json` 和 `module-get-production-proof.jpg`。
这些是当前内置浏览器渲染及HTTP证据，不是Safari或真机冷加载验收；首次全部秒开的目标仍未完成。

部署stage `host-upgrades/module-get-v1`；脚本SHA `eeb730baf59882e46957d84686a74ce85c3175534a063ebd1f276344e8ae1a64`，
plan SHA `dadc1d1d853f3e0b350b7278c4493a70d716419c5e5fac7e2ad7d56ec03b6db5`。
准备及推广均自然退出0；精确逆变换恢复v15 FRAME且HOST不变，原6入口CAS、历史数据报告保留及条件回滚不改。

v15的作者/就绪隔离trace另发现插桩缺陷：`installCigen.toString()`在新realm重建后无法访问外层QA闭包，
导致child-phase的记录抛ReferenceError。`author-ready-boundary-actual-ui-v1.json`原样保留为失败采集，
其中dropped=0不等于事件完整，尾部计时可能受插桩错误影响，不能据此确认child实际启动阶段。
后续只修隔离v2的显式realm bridge并先做重建函数消息合同，未把该插桩加入产品。

修正后的v2已实际运行，仍封存v15基线，不与v16产品混同。正面565ms、立即完整背面3176ms，
626条/688次/native ready及1个词源子框保持；frame/host上限均未丢记录。
`author-ready-boundary-actual-ui-v2.json`记录child-installed自产在总线3482ms，父接收差8.8ms；
此前3047ms的gate已native ready/fonts loaded而child尚未init。这支持此轮child脚本开始较晚，
不能单凭该记录把原因指定为srcdoc解析、父页面任务或浏览器调度。
后续两条child-measure消息另有约143–164ms接收延迟，说明父交付等待也可能混入观察；不将这些样本推广成固定耗时。
