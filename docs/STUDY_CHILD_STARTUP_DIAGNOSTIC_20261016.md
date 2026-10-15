# 2026-10-16 长卡词源子文档启动对照

初始诊断从 `study-web-host.v12-source-wrapper-gzip`、代码检查点 `7603378` 开始，先只写隔离诊断页，没有替换正式产物。随后采用的一处布局采样优化及v13实际推广单列在末节；卡片、数据库或APKG未修改。首次立即翻长卡的性能目标仍未完成。

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
