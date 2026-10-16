# 完整就绪检查的节点成员缓存

本项以正式网页 v18 为基线，已条件推广为 v19；继续同一性能目标，不改 PostgreSQL、APKG、内容、计数或最终显示门槛。
当前一次完整长卡阶段实测中，背面 gate 等待约 4,933ms，检查 483 次，
同步检查累计约 847ms；主文档字体和 native 已就绪，主要仍在等词源子页。
该同步时间包含节点查询、状态及几何检查，不能全部算成可节省的查询成本。
此前仅六次检查的较小样本不足以代表这个长等待场景。

## 修改范围

- 仅在一次 `waitPrepared` 生命周期内缓存 iframe/native payload 两类成员列表。
- 通过 MutationObserver 的 childList/class 变更和读取前 `takeRecords()` 失效；
  新增、移除、搬移或修改 class 后，原选择器重新查询，不固定一次列表。
- 沿用原分支和短路顺序：先 iframe/child error，再 native、字体和完整几何。
  原 child 签名/宽度、每次 native 状态、字体、三次稳定样本、rAF 和共享十秒期限均保留。
- Observer 不可用或安装失败时走原查询；完成、取消及错误均断开并释放列表。
  不改成事件驱动 gate，不增加跨卡缓存。

## 验证与推广门槛

先在 `/tmp` 做原逻辑查询重复的 RED，再证明缓存减少无变更查询，同时新增/删除/class/未送达变更等结果等价。
独立复核实际 diff；使用 v18 同一个最小计时口径实际对照，正文、次数和完整显示不减少。
减少查询/CPU 与整卡墙钟提速分开报告，不以高系统负载下的单次样本承诺全部秒开。
只有保真与资源开销证据成立才接入共同生成器并条件推广三书；后续新书共用该逻辑。

当前阶段证据：`output/study-catalog-20261015/v18-minimal-gate-actual-ui-v2.json`。
该页只增加有界状态/时钟，HOST/FRAME 的逆变换精确回到正式原码，12项窄合同通过。
当前为 IAB 局域网实测，不冒充 Safari/手机性能验收。

## 已审公共实现与实际对照

共同生成器已接入同一缓存；以下隔离验证通过后，已替换三个正式入口（见下节）。新 FRAME 为
`d7e60fccd7fc6158f8c29f5128a993e14e07e591c91b3a948b70662a27a1b59a`，
移除本项 helper/wait 改动精确恢复原 `db9ad022…4513d`；HOST 与数据均不变。

- 真实 MutationObserver 合同覆盖15种情况；500次无成员变更检查中，两类查询各由500次降至1次。
- 实际接入后的5组、33项测试通过（96.850秒）；独立复核共同运行时与已审候选逐字一致，未发现P1/P2。
- IAB 最长卡实际80次检查中，两类查询各3次，同步检查累计37.1ms；完整背面等待3,670.8ms。
  之后重新打开旧实现为52次检查、115.9ms同步检查、3,145.5ms背面等待。
  前一个旧样本为483次检查、847.2ms同步检查、8,860.3ms背面等待。
  这些样本支持减少重复查询及检查工作量，不支持宣称整卡稳定提速或已经秒开。
- 新旧8项完整内容对照均相等：92,832元素、626条例句、578历史引用、native就绪、
  688次物理计数、1,144个根身份、1,716份历史HTML摘要与可见文本摘要；页面高度亦相同。
- 实际执行 more背面→mosquito正面→more正面→手动翻回more背面，全文与688次保留。
  此项不是准备期间取消或Safari/手机性能验收。

证据位于 `output/study-catalog-20261015/`：
`v18-gate-members-actual-ui-v1.json`、`v18-gate-members-content-actual-ui-v1.json`、
`v18-gate-members-navigation-actual-ui-v1.json`、`v18-gate-members-baseline-after-actual-ui-v1.json`；
原始截图为 `v18-gate-members-complete-proof.jpg`。
按资源工作量减少且内容保真采用；六入口条件推广、正式页面和干净安装见下节。

## 正式三书与安装

源码节点 `12aea81`；prepare/promote均自然exit0，仅以内容/stat CAS替换三index和三COMPLETE。
脚本 `promote-study-gate-members-cache-20261016.py` SHA为
`94df302804a05265288ab71a672bfd65152c4a8e2085da3f8c85dd1ef53b7189`；
外部seal SHA为 `bc66cae36ceb689593fe63ffbee6a2d8459f14fea7ebdeb44a3642850cec408d`；
plan SHA为 `d797dcfa4a76daf6de59cd54a31ef2178640996cf6dc0815792f38d075cabd78`。
stage为 `host-upgrades/gate-members-cache-v1`，含原入口备份与有所有权条件的回滚。
独立审查修复合法catalog源链接的误拒绝，11项临时目录合同通过，无剩余P1/P2。

三书实际LAN config/公共HOST与本地正式封印相等；LAN服务会注入既有bootstrap，不能宣称HTTP原HTML字节与本地文件相等。
IAB实点2027 more、2026 remote、刘晓艳ambition的正面和完整背面；正式more的8项全文/历史/计数对照与高度继续全同。
证据为 `v19-formal-{deployment-current,lan-http,three-entries-actual-ui,more-content-actual-ui}-v1.json`；
原始截图为 `v19-formal-more-complete.jpg`。本轮不将IAB冒充Safari或真实手机。

仓库外干净安装 `wheel-current-install-qa-v20.json` 通过：133包文件逐SHA精确，MathJax25项+SOURCE、LAN模板、实际target导入与两个CLI均通过。
报告SHA为 `c3d8f0d00190f5bbd37a6dfd1115ffeaa2562d38fb7e9572064caff0b4224207`。
这个v20是安装报告编号，实际网页运行时为v19；PG、APKG和媒体未重写。

## 剩余首次等待：已排除的配置重发方向

当前v19仅增加有界时钟的诊断逆变换精确恢复原逻辑，4项合同通过。
`v19-child-clock-actual-ui-v1.json` 的完整背面为4,299.1ms；子页timeOrigin至最早监听器安装约2,948.6ms，
父收到installed至iframe load约281ms。前次配置在监听器安装前发出，首次收件来自load后的重发。
只提前重发配置不能缩短2.95秒大头，且父load仍会清空ready、子页sent去重可能不再上报相同ready，故不采用。
本次未改握手或就绪协议；不能把浏览器调度/本机换页时间直接当作可节省的产品CPU。
Safari操作接口本次再次超时，当前Safari/手机性能和首次全部秒开目标仍未完成。

用户随后复测当前入口反馈“都卡，都不止三秒”，性能明确未通过；此前误选的“首次约1秒内”已撤销，不作为验收证据。
当前仍在区分首次打开、切词和重复翻面的具体阶段，不能将用户反馈缩成仅more冷启动。

## 后续定位：初始化长任务，尚未形成新产品修复

`v19-child-longtask-passive-actual-ui-v1.json` 在开始后15秒不查询DOM，再读取已完成记录：
完整背面4,217.7ms，父级同一个1,783ms长任务覆盖词源子页首次执行的大段等待。
同任务可能在多个同源observer重复出现，不能把各scope记录相加。

已打开的作者分段诊断页后来完成，记录保存为 `v19-author-refresh-clock-actual-ui-v1.json`：
首次正面688.5ms、完整背面2,308.4ms；作者执行合计约172.1ms，batch最终刷新225.2ms。
重复pin第二轮合计约18.3ms，不能靠跳过它们解释或消除数秒等待；原执行顺序和副作用继续保留。
本次仅证明时序分布和波动，不代表当前Safari/手机验收通过。

在连接正文后、首批作者脚本前增加单次timer让行的隔离候选已停止：
child提前ready、父load清空状态、相同签名去重的反例会让原严格门槛超时。
10项局部检查不构成安全通过；未安装该候选，正式仍为v19。
停止封印SHA为 `e20dd404e482105473ed43c7592ac97c7f392d9b129c553be89774f1b456f5a0`。

## 实际客户端路径诊断（临时独立页）

正式入口未变，另建同目录QA页面观察shared或原wrapper兼容路径及前两次顶端翻面。
配置和FRAME原字节不变；HOST仅在该页保留原有有界错误output，collector最多6次同源HEAD，
不发送全文、stack、身份或学习记录，也不自动翻面、不扫描整页或测量布局。
消息核对frame source、origin、card、token和answer变化；兼容路径不冒称完整提交。
该记录是点击dispatch至原完整提交信号，不能替代实际绘制或触摸响应验收。

16项collector合同、4项安装失败注入及独立复核通过；并发替换/改写的文件不会被回滚删除。
安装仅新增三个带摘要的QA文件，正式index和数据不改。复核封印及本机IAB实际收件分别为
`client-diag-reviewed-v1/acceptance.json`、`client-diag-installed-v1.json`、`client-diag-own-iab-receipt-v1.json`。
本机在已预备后翻背面/正面信号为421.1/258.8ms，不能用它推翻用户全部超过3秒的反馈。
已请求用户从发生卡顿的浏览器打开该独立诊断页；真实客户端结果尚待取得，性能仍未通过。
