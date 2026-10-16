# Safari共同校验实现：隔离候选计划

当前三个原入口已采用共同源码 `206edcc`。相同实际源的隔离 Safari 首次完整背面样本分别为16.793秒、1.910秒与0.338秒，仍未全部达到秒开；原入口正常翻面另有实际复核。
本文件按时间保留调查过程，当前采用情况见[共同源206edcc与三个原入口](#共同源206edcc与三个原入口)。
关闭软件后的复测与未推广的最新候选另见[本轮实测](#关闭软件后的复测与共同扫描候选)。

以下为v20阶段的历史记录：首次完整背面当时仍未通过性能验收。局域网接线已经统一，但同一Safari仍出现54–69秒等待，
不能把接线修正当作主因修复。带16条上限的digest观察取得两次约32秒的大摘要；
其完成时刻接近，与Worker停机后本地重算相容，尚未证明这一条具体链路。

## 新的实际证据

复用现成`_qa-sha-wasm-compare-v1-20261016.html`，原文件SHA
`4418d92d28d459eae40ccbdc4bda9d6cc7007331d862f45f8880b649f45ea03f`。
电脑Safari实点完成8次摘要，第二轮反序，均匹配固定输入原SHA：

| 完整输入 | fastJS两轮 | 固定WASM两轮 |
|---|---|---|
| prepared index，4435220字节 | 2185/2666ms | 442/507ms |
| prepared native module，1949068字节 | 1241/1152ms | 156/178ms |

WASM编译59ms、实例化与adapter初始化34ms。计时不含网络/输入解码、hex与结果渲染；
这是同步主线程摘要对照，不等于整卡、Worker或手机验收，也不证明浏览器是否禁用了JIT。
本机证据`v20-safari-wasm-visual-observations-v1.json`明确标注为4张原生实拍的人工转录，
不是冒称下载得到的浏览器JSON。当前正式算法未改。

## 执行范围和次序

1. 在隔离目录准备一个共同LAN runtime候选，使用现有已固定版本、许可与SHA的WASM/adapter，不重新下载依赖。
2. 保留同步BufferSource快照、Promise与错误语义、2 Worker/8 job/64MiB/10秒期限、id/transfer验证。
   大输入可在已有Worker及本地恢复路径用固定WASM；不可用或执行失败仍用原fastJS。小输入保留原路径。
3. 先建立实际行为检查与原基线失败，再实现及验证：WASM命中、不可用/故障恢复、多次调用状态隔离、跨block与大输入原SHA；
   复用已有BufferSource/worker合同，不用源码字符串断言代替行为。
4. 独立审查后只建新QA；同一Safari实际验证完整内容、首次立即/重复翻面及普通卡。
   必须覆盖2027 more，以及更大的2026/2027 the和刘晓艳social，不能只测more就称三书全部秒开。
5. 只有候选通过后才决定是否进入共同生成器和正式入口。部署需同时考虑当前代理固定读取runtime SHA；
   禁止直接覆盖已运行代理所读取的共同文件造成503。条件部署、备份与回滚另行验证。

隔离实现与首轮验证估计15–25分钟；这是当前阶段估计，不是整个性能目标的完成承诺。
不改安全设置、不减内容/次数/校验、不改PG/APKG/真实Anki或学习数据，不按书名或年份复制不同逻辑。

## 隔离整卡结果：尚未采用

共同候选 `31181e27479e651035faa2612b1f36333e9079fa195e20d5b280d008aee9bfb7`
复用固定 WASM；大输入进入原 Worker／本地恢复路径，小输入保留原路径。
30 项行为检查通过，包含原 worker 合同、大输入原 SHA、WASM 故障恢复和状态隔离；
独立审查无 P1/P2。新建 QA 的结构和时钟合同另行通过，正式运行时仍为 `ea3c80d4…e109e6`。

实际电脑 Safari、`http://192.168.3.5:8771`，同一候选：

| 隔离页面／卡片 | 首次完整正面提交 | 立即请求完整背面 | 结论 |
|---|---:|---:|---|
| 2027 红宝书 more，默认无摘要观察 | 2682ms | 8383ms | 完整提交；未达到秒开 |
| 2027 红宝书 more，最多 16 条摘要观察 | 2850ms | 9368ms | 完整提交；观察可能影响耗时 |
| 2027 刘晓艳 social，最大完整数据卡 | 2463ms | 715ms | 此卡完整提交 |
| 2027 红宝书 the，约 47.9MB | 13010ms | 90 秒内未收到完整背面提交 | 失败，顶部仍禁用；不得推广 |

以上是原完整就绪门槛的提交信号，不是绘制完成或稳定上限。`social` 的结果不能推广为全书秒开；
`the` 超时后已关闭本次自建测试标签，避免继续占用资源。2026 的更大 `the` 尚未测试，
先定位已出现的相同类型卡住，再继续覆盖。正式三个入口和所有学习数据未变。

more 摘要样本中，19.4MB 完整包和 17.2MB 原 wrapper 分别约 3378/3062ms，区间重叠，不能相加；
后续 FRAME 摘要被 16 条上限截断，因此不能把剩余等待直接归因于 DOM。
同一 Safari 的 `127.0.0.1` 原生摘要对照为正面 2573ms、背面 3677ms；
源、缓存及本机传输条件不同，仅作方向对照，不能充当局域网验收。

本机原始结果位于 `output/study-catalog-20261015/`：
`wasm-more-safari-first-v1.json`、`wasm-more-safari-digest-v1.json`、
`wasm-large-liu-social-safari-v1.json`、`wasm-large-redbook2027-the-timeout-v1.json`。
后两项附有同一页面的一次性本机回传及原生截图，记录实际 origin、卡片和候选 SHA。
未经观察的 Worker 分支命中和异常根因仍不作结论。

## 后续定位与原生已知摘要能力

more 的新有界观察只记录至少 256KiB 的摘要，11 条均成功；正面 2847ms、完整背面 10735ms。
其中背面 source/expanded 两份约 16.2/18.2MB 的校验分别约 2589/3334ms，仍有重叠。
错误列表为空仅代表此次监听未收到错误；摘要的 Promise 观察本身可能使拒绝被标为 handled，
FRAME 载入前的错误也可能漏记，不能由此证明无异常。

最大卡 the 的五点隔离观察保留原 HOST／校验／完整就绪门槛：
完整正面 10837ms，完整附接接受 11682ms，背面两份 proof 通过 20893ms；
随后 90 秒超时，父页面未收到 body 接入信号。
这只是接收侧记录，不能据此断定 FRAME 尚未执行到正文接入，也不能认定某一步骤为根因；
下文新增的 producer 时钟已修正这一判断。
原始手动下载与终态本机回传分别保存在 `wasm-largest-five-stage-terminal-safari-v1.json`
和 `wasm-largest-five-stage-server-v1.json`。

同一 HTTP 局域网 Safari 的独立能力页验证了本地 Blob 上的 `fetch(...,{integrity})`：
ASCII、中文／emoji／组合字符／换行、4MiB 固定字节三组，正确摘要成功、单字节篡改和错误摘要拒绝，
共 9 项通过。4MiB 正例 fetch（含完整性校验）69ms、读取响应 1ms；
构造输入和逐字节比较也计入的整个测试为 706ms，不能把 69ms 称为整项或整卡耗时。
此页没有调用 `crypto.subtle` 或传出源内容；规范依据为 [Fetch 完整性处理](https://fetch.spec.whatwg.org/#main-fetch)。
原始浏览器下载为 `blob-integrity-capability-safari-v1.json`，附有原生实拍。

一个共用已知摘要验证 helper 已在 `/tmp` 建成并独立复核，10 项 helper 与 4 项实际调用点合同通过，
保留能力探测、同步快照、严格 pin、超时清理与同一快照的原 SHA 回退。
真实完整包生成的 SRI-only more 隔离 QA 保留正式共同摘要脚本、真实 wrapper contracts 和原完整 gate，
仅换 HOST/FRAME 已知摘要比较；没有插入 WASM 候选或换正式入口。
实际 Safari 默认无摘要观察：正面 4233ms、立即完整背面 7488ms，626 条例句／688 次词频可见。
原始结果 `sri-more-safari-first-v1.json` 与同次本机回传、原生截图已保存。
**仍未达到秒开，不采用为正式版本。** 固定输入的能力测试不能替代此整卡结果。

追加的 warm 边界实测曾使调查集中到 `JSON.parse(raw)`／`Projection.prepare`：
正面 6140ms、背面 proof 17505ms、native payload load 完成 21087ms，
到 90 秒超时仍没有 projection 返回信号（`wasm-largest-warm-stages-safari-v1.json`）。
但缺少接收信号不能证明 producer 没有执行，不能据此排除后续步骤。

接着只在隔离 QA 中替换该处 task 调度并加入 producer 时钟，保留原算法、内容、
检查、128 项／8ms 条件及完整就绪门槛。实际 Safari 正面 7221ms，背面仍在 90 秒期限内失败，
随后原有资源失败回退出现；候选不采用。
本次 `Projection.prepare` 在 FRAME 内从 `1792155197852` 到 `1792155198804`，约 952ms 完成；
3809 次摘要累计等待 490ms，71 次让行累计等待 358ms，未走调度回退。
正文接入时 producer 时钟为 `1792155202678`，消息到达父页面却已是测试的 119215ms。
以同次 proof 消息对齐，两者相差约 87165ms。
**这修正了前面“Projection 没返回”的推断：准备已完成，长延迟出现在正文接入之后的工作或消息派发中。**
尚未将延迟归到某个函数，也未证明正式原 timer 的分支表现。
`projection-task-the-server-v1.json` 保留 producer 时钟和累计值；
手动下载在原 FRAME 被回退替换后计数 getter 已为空，不能用这个空值否定先前已收到的记录。

下一轮只加入真实异步阶段计时，区分 bank 来源绑定、group 分组、编号脚本和 batch 收尾刷新；
不再只量异步 `AnkiSlimApkgHydrate()` 的同步入口。正式代码与学习数据未改。

## 原生阶段实测与内存环境复测

新的有界 producer 计时覆盖真正的 `bank.ready`、Group、两次编号执行和 batch 收尾，
跨异步等待捕获本次观察函数，旧会话完成不能结束新会话的计时。
原 timer 的 A 页正面 7978ms，90 秒背面信号超时，尚未收到正文接入信号；
同次 3 秒进程取样主线程 1900 个样本中 1860 个处于 Mach 等待。
这是采样窗口中的等待，不能单凭它指定 timer 或其他函数为唯一根因。

A2 页复用前述已审调度候选，保留原编号与 Group 算法，获得以下真实 producer 区间：

| 阶段 | 关闭不用的软件之前 | 用户关闭软件之后，同一 A2 原逻辑复测 |
|---|---:|---:|
| 首次编号执行 | 38913ms | 13371ms |
| 第二次编号执行 | 1ms | 0ms |
| batch 收尾刷新 | 5696ms | 1108ms |
| bank 安装至 ready | 5755ms | 897ms |
| Group 安装 | 31266ms | 10498ms |
| 完整背面结果 | 超时后原页面回退 | source-error 后原页面回退 |

前一轮 Group 区间为 epoch `1792157239553..1792157270819`；
21:27:23.220 的同次进程采样确实落在此区间，主线程 1743 个样本均在 TreeWalker 分配引发的同步 GC 链，
其中 1717 个栈顶为 `AXObjectCache::remove`，父链包含 span 析构。
不能据此改称样本在编号的 `getComputedStyle`；它证明本次 Group 内出现大量节点回收。
原 Group 每条翻译深克隆后只保留字符串，使这些临时 span 子树可被回收。

静态审计另核实 5794 条原例句，其中 5540 个 badge 需要改写，254 个已正确；
这项未执行计算样式，不能替代浏览器可见资格判断。
两个隔离候选分别改为全轮先读后写编号，以及从原翻译 textContent 等价剔除标签文本而不深克隆。
编号 14 项行为检查、翻译原生 12 项／prepared 与适配 16 项检查通过，独立审查无 P1/P2；
未知 pin 不适配，原文本、计数、身份、校验与完整就绪门槛保留。整卡性能尚待候选实测，未部署。

用户关闭软件后记录的交换空间为 42396.25MiB、系统可用内存百分比 27%。
原逻辑自身已明显加快，因此后续候选必须与这次复测比较，不能把环境改善记成代码收益。
原始下载／本机回传／截图与采样分别保存为 `native-producers-task-a2-*`、
`native-producers-a2-pressure-adjusted-*` 和 `native-producers-original-*`，位于前述本机证据目录。

## 两处算法候选的实际整卡结果

同一较低内存压力环境，G 页在 A2 的校验／调度基础上仅加入两阶段编号与无深克隆文本读取。
Safari 首次正面 5332ms，立即请求完整背面 20675ms，原完整就绪门槛通过，未进入原页面回退。
浏览器可见 9466 次词频和 5794 条例句；返回正面、再次背面均观察到正确按钮和内容，未另测重复翻面的毫秒数。

| 相同原生阶段 | 同环境 A2 原算法 | G 算法候选 |
|---|---:|---:|
| 首次编号 | 13371ms | 2039ms |
| Group 安装 | 10498ms | 2645ms |
| bank 至 ready | 897ms | 1040ms |
| batch 收尾刷新 | 1108ms | 983ms |
| 完整背面 | 失败回退 | 完整提交，20675ms |

这证明两处算法减少了相应阶段的实际成本，也说明不能把每项阶段都称为加速。
**首次完整背面仍超过 20 秒，尚未达到秒开目标，正式三个入口未更新为 G。**
原始浏览器下载 `native-producers-task-g-safari-v1.json` 的 SHA 为
`fc60764ad92d85485cff1f95b11dee01a5053acf200d5af35fb65e49daf22d6e`，
附同次本机回传、完整背面截图与重复翻面功能观察。

两处纯算法已接入本分支共同代码：旧 9d 编号脚本经过原资源 SHA 和全文守卫后执行与新导出相同的 d341 模板；
be392 的 Group 读取也在原 prepared 资源校验后采用同一已审适配器。
10 项定向 Python 检查通过，无跳过，包含编号 14 项、Group 16 项和实际调用点 10 项合同；独立审查无 P1/P2。
本地新 FRAME 为 `30a9e2d88b2b930bea358e062bdee7e7494e6dd36453469f7d8daf452a3a9abb`，HOST 未变。
这次源码提交只包含两处算法及其严格接线，未把 G 的 WASM／调度观察组合部署到正式入口，也未把 20.675 秒当作此源码组合的实测值。
源码安装核验 v22 的 135 个包文件在 source／wheel／installed 三处逐 SHA 相等，两个新增模板均可从安装包读取，
25 个离线公式资源与 SOURCE 清单完整，两个安装后的 CLI 在仓库外 `--help` 成功；全程没有连接 PG 或生成 APKG。
报告 `wheel-current-install-qa-v22.json` 的 SHA 为 `65c66d9644d251b0f79112061a166cf4f7766b052c940d0c3ed6021305da3bac`。

## 已知摘要原生校验与无额外模块对照

SRI-G 在同一 G 算法基础上，仅把六个已有预期 SHA 的比较接到已审的私有原生校验 helper；
原浏览器完整资源、错误摘要、失败回退、不可变输入及顺序门槛均保留。
实际 LAN Safari 首次完整正面信号 1851ms、随即请求完整背面 16378ms，完整就绪门槛通过。
页面可见 9466 次词频、5794 条例句和“返回正面”；这不是绘制完成或全部卡秒开的承诺。
原始下载 `sri-g-the-safari-v1.json` SHA 为
`13f6df05f32c95e0ec9733e12ad3d6fbe610bf849287d0ffc1cb6f5415a39a79`，附同次本机回传及页面截图。

随后仅去除额外 WASM 块，保留相同 SRI、调度、算法、时钟与完整门槛。
实际 LAN 返回重新注入原共同 SHA 脚本 EA3，源字节与 SRI 相符，未修改代理或共同脚本。
Safari 首次正面 1741ms、立即请求完整背面 20277ms，亦完整提交，页面统计及例句数相同。
原始下载为 `sri-g-no-wasm-the-safari-v1.json`；这是一轮对照，不能把 3.899 秒差异全部归于 WASM，
更不能把它称为稳定收益。两个隔离页均未替换正式三书入口。

只读流式结构审计进一步核实：the 的 414433 个原始元素中，默认收起 details 包含去重后
242325 个（58.47%）；14 个义项面板占主要部分，并含完整 occurrence/chunk 标记及过滤交互。
相邻且全部属性完全相同的 chunk spans 只有 20 个，占 254457 个的 0.00786%，
简单合并 span 无法实质解决卡顿。此项没有删除、延迟展示或改变任何原句、边界及计数。
结构证据保存在 `closed-details-structure-v1/` 和 `adjacent-chunk-structure-v1/`。

六处原生已知摘要比较及有界任务调度随后接回共同生成源：helper 保持已审 eddf7d 原字节，
调度生产模板只移除 QA 计时、query 和强制原 timer 模式，原 128 项／8ms 条件、timer 回退、
单 pending、2 秒 watchdog、会话身份及关闭处理保留。10 项定向检查通过，独立审查覆盖实际 12 个文件，未发现 P1/P2。
当前源码 HOST 为 `aed67c9ce6e87662cef875fad6c563259b32424f736a7ab63172e409125c9984`，
FRAME 为 `33f4fcaa2b907013990136ec334fdcf9418deeaa055ac4215d0e3637ed901303`。
这份无诊断源码组合还没有三书 Safari 成品时延验收；16.378／20.277 秒仍只属于前述两个隔离页。
没有整合额外 WASM、修改正式入口或数据。冻结及 RED／GREEN 证据见本机 `common-integrity-task-source-integration-v1/`。
本地源码提交为 `179a967`。v23 干净 wheel／安装核验的 137 个包文件逐 SHA 一致，
两个新模板及实际 HOST／FRAME／HTML 导出一致；CLI 和离线公式资源通过，PG 连接尝试为 0。
报告 `wheel-current-install-qa-v23.json` SHA 为 `ad8ebbf8e4bdf57d216b5762035dae22e7de5cc55b02ad3d572f39b46ca43f61`。

## 收窄 Group 的祖先遍历

再一项隔离候选仅把已知 Group 的 ranges 遍历截在本次文本容器根（含根自身），
去除两处由祖先关系保证恒真的 contains；所有调用点均显式要求匹配元素位于该根内。
原 SHOW_TEXT、UTF16 偏移、Map 顺序、chunk 图、标记、审核内容搬移、筛选和 dispose 保留，
四个 exact 边界及 be392 pin 严格守卫。11 项窄合同和独立审查通过，未知 source 原样返回。
无额外 WASM 的同条件 Safari 对照：Group 从上轮 4547ms 降至本轮 1615ms；
本轮正面 3425ms、立即请求完整背面 18110ms，页面仍可见 9466 次词频、5794 条例句。
这是单次不同运行间的比较，不能把全部时差归于算法；完整背面仍未达秒开。
原始下载 `sri-g-ranges-the-safari-v1.json` SHA 为
`5d250fed54f4a98838fcfbdc00b1dc7d2674389262c0fc9e40a6094965c2d622`，
候选源码和组合材料分别存于 `bounded-ranges-reviewed-v1/`、`bounded-ranges-qa-reviewed-v1/`。
这处适配随后接回同一个共同生成函数：模板保持 0af6 原字节，在已校验资源的 lookup／task／no-clone 之后执行，
3 项定向检查和独立审查通过。移除唯一新增模板与调用可逐字恢复上一已审 FRAME。
新 FRAME 为 `ecc6ec8898a6077500d2b02c58fbbb2df79032528dd1af716b1cee392bb68948`，HOST 仍为 aed67；
这份实际生成代码的三书浏览器结果另行记录，不把隔离页 18.110 秒冒认为它的时延。
该节点为本地 `ec6daca`。随后 v24 对新源码及新增 ranges 模板重新做干净 wheel／安装核验：
138 个包文件逐 SHA 相等，新模板及实际运行时导出相同，CLI 和 25 个离线公式资源通过。
报告 `wheel-current-install-qa-v24.json` SHA 为 `cc31604130ad9282d9091ac713bfbde9937d99c09043bb47c0a381f3e68bd172`；
PG 连接尝试为 0，未改 APKG、正式入口或服务，v23 只作为其当时源码的历史证据。

## 实际共同生成源 ec6daca 的三书复测

三页均从该提交的完整隔离包真实生成，HOST／FRAME／HTML 与源冻结逐字相同。
使用同一页内时钟模板，只观察原完成信号并立即请求一次背面；不再注入旧 G 的 producer、task 或 WASM。
同一 Safari 保留现有浏览器缓存，记录的是新页面内首次完整提交信号，不冒称空缓存或绘制完成时间。

| 样本 | 首次正面 | 立即请求完整背面 | 页面结果 |
|---|---:|---:|---|
| 2027 红宝书 more | 1259ms | 3068ms | 完整，688 次／626 条例句 |
| 2026 红宝书最大 the | 2075ms | 90 秒内无完整背面信号 | 未通过，随后观察到原卡加载路径 |
| 2027 刘晓艳最大 social | 943ms | 327ms | 完整，215 次／216 条例句 |

more 的首个义项仍为 305 次、合并展示 283 条原文；2026 年筛选为 14 次／14 条原文，
句子与依据可见，返回正面与重复背面正确，未另外量重复翻面的毫秒数。
原始下载为 `source-final-*-safari-v1.json`，完整页面及相关操作观察附在同一本机证据目录。

**本轮整体验收未通过，三书正式入口未推广。** 2026 实际采用已知旧模块 5c361／prepared7f16，
而前述三处 task／no-clone／ranges 适配只接到 be392；lookup 已有两种原源码的共同接线。
后续先核对两套已封存原源码及 prepared 形态的相同 exact 边界，再把同一算法用于两个已知来源。
这项兼容修复尚不能替代修复后的 Safari 验收，也不改变秒开目标仍未达到的状态。

四份真实输入的 source SHA 核验后，task 两处、no-clone 两处及 ranges 四处边界均各恰好一次，
两个已知模块的这八个边界逐字同形。修复只把三个私有适配器的批准来源统一为 `[5c361, be392]`，
算法正文逆改 guard 后逐字恢复原已审模板，旧 be 输出保持相同；未知来源原样返回，八处形态漂移逐项拒绝。
raw5c 不含 prepared 阶段的 warm-cache 注入，因此实际 lookup 执行正例严格使用原 prepared7f16，
未用 raw 冒充 prepared。4 项定向检查及独立审查通过。
新 FRAME 为 `bf8e24ec9730f4749f556baf3885f780a50aac3191366eb6c74ebb513f64d577`，HOST 仍为 aed67。
旧推广计划因源码冻结变化已失效，正式原入口保持不变，等待新源三书实测。

## 双来源共同算法 70fd1e7 的实际三书结果

同一实际生成源重新生成三页并实测：

| 样本 | 首次正面 | 立即请求完整背面 | 实际可见词频／例句 |
|---|---:|---:|---:|
| 2026 红宝书最大 the | 2237ms | 22184ms | 9466／5794 |
| 2027 红宝书 more | 2038ms | 3612ms | 688／626 |
| 2027 刘晓艳最大 social | 717ms | 255ms | 215／216 |

全部通过原完整就绪信号并观察到完整背面。2026 的旧模块遗漏已修复，但最大卡仍需 22.184 秒，
**这轮功能通过不等于性能目标达成**。浏览器缓存保持现状，未将计时称为空缓存或绘制完成。
`source-dual-three-acceptance-v1.json` SHA 为 `572eac3d32b18cec6499b26ef2dd1a095320d63c2d679d4ff31633ad5a581fe0`，
内含三份原始下载 SHA，附三张实际背面截图及同次本机回传。
v25 干净安装核验重新覆盖这次新 guard 的138个包文件和实际运行时；
报告 SHA 为 `91f5318e00bde987e2fd58eb6feb05de64ed7affe63a41f229b747627109ed5a`。

原入口推广的第一次 apply 在写入前被 staging manifest 的 ctime 封印检查拒绝，
三个原入口均未改、STARTED 未创建；内容 SHA 及其它 stat 字段相同。
保留失败现场，先查明封印后元数据变化原因，未关闭或放宽完整性检查。

## 三个原入口已采用共同源码

自有测试文件复现 Documents 下延后的 ctime 变化，内容 SHA、身份及其它 stat 字段不变；
另一个现有持久目录在有限的25秒观察中稳定。这些观察不证明具体后台进程或永久稳定性。
推广备份改放在 `~/Library/Application Support/AnkiStudyCatalog/exports/20261015/host-upgrades/dual-native-originals-v4/`，
保留全部原身份、内容和完整 stat 校验；准备阶段仅在内容及其它身份字段严格相等时重封新 stage 元数据。
独立增量审查通过后实际 apply 成功，只替换三个原入口的 index，COMPLETE、源卡、媒体与目录绑定保持不变。

v4 plan SHA 为 `e065635cdd02ef1735d06a4f93b0f7c4b7219ed5a891f64354cf1c5ebfc312f8`；
实际 APPLIED receipt SHA 为 `a30c059a93ddee845e8ee9f53fe84df75274f676e293a890f600669a39ac77ae`。
三个原 index 的新 SHA 分别为：

| 书籍 | index SHA256 |
|---|---|
| 2027红宝书 | `1ebb3072032d995a3d5916e0ac01a6fc36e9999533b5bde1b0aa872e737d6e1b` |
| 2026红宝书 | `79e94bcd7711ce2c61e20b5d85f0f85b620bed67daebcff407d9dc319fa3cdf3` |
| 2027刘晓艳 | `20ad4683ff3f3a3ad06660cbee144e073a2986295fa9a559bc9dd1e09a815b24` |

独立只读核对实际三份 LAN 原入口：HTML 配置、FRAME `bf8e24…`、HOST `aed67…` 与共同源码一致，
HTML/HOST 的 identity 与 gzip 解压原字节相同，EA3 bootstrap 的原字节及 SRI 正确。
报告 `original-index-rollout-v4-post-http-v1.json` SHA 为
`8fb23742e81f5e41ea92fe12f603d4c4e888a1be76186a55dbeed0a9700978a0`。
随后在电脑 Safari 打开原2027入口，确认旧卡组／单词目录、完整背面、688次词频与626条例句可见，
保存 `original-index-rollout-v4-more-ui-v1.json` 和完整页面截图。
这次正式入口冒烟检查没有重新计时，不能覆盖上表首次背面的3.612秒或声称全部秒开。

完整旧 index 与回滚材料在上述 v4 目录；需要撤销本轮时使用同目录 `installer.py rollback`，
它只回滚仍属于这次推广的 index，拒绝覆盖外部后续修改。本轮没有发布远端或重新生成 Anki 包。

下一项结构调查确认关闭的14个义项占约24MB、24万个后代节点，但简单把它们塞入 template 不免解析，
字符串暂存又会绕过原 native 对实际 DOM 的准备与分组。此候选尚未采用；
不能把延后处理正文当作已经实现完整秒开，也不能为省时跳过实际来源和内容校验。

## 后续减少无效初始化计算：仍未达标

共同源码 `675534d` 避免编号脚本将自身的 badge 写入再触发整表扫描，仍按真实节点身份逐条识别，保留外部修改与全部记录的 prune。
同一节点也加入分组的必要粗桶；只有粗桶至少两行才计算原完整 chunk 图，实际物理身份、usage、图、目标与审核合并不变。
编号15项、共同算法／接线6项及原静态正文2项定向检查通过；独立复核后建立本地 Git 节点。

随后 `a639100` 将 ReadingBank 预热缩到已验证 binding 的实际唯一英文，原 buildIndex、固定侧车摘要、实际 process 的文本／哈希／范围与异步后重核都不变。
单卡流式统计为15,336处文本、5,354种唯一文本，binding命中533处／201种；它不是应删除的内容数量。
23项实际IIFE／调用合同及10项相关检查通过，实际接线独立复核后本地提交；未改业务库、卡包或正式三入口。

| 实际源 | 电脑 Safari 首次正面 | 立即请求完整背面 |
|---|---:|---:|
| 已推广源的阶段计时对照（`cae3121`，产品字节同`70fd1e7`） | 2266ms | 21642ms |
| `675534d` | 1752ms | 20962ms |
| `a639100` | 2337ms | 19409ms |
| `ac3be0b`，加入 Fine 两阶段探测 | 2071ms | 20730ms |
| `6534cbe`，Slim 资产调用已有快速校验器 | 2865ms | 15421ms |

五次均观察到9466次词频、5794条例句和完整背面。现有浏览器缓存保留，均为单次完成信号，不是绘制完成、稳定上限或每项算法的独立收益。
时钟页的 HOST 同用已审 data classic/defer 方式，少一次外链 HOST 请求；不可拿它们作与原入口完全相同网络条件的绝对对照。
原始报告依次为 `current-source-2026-the-stage-safari-v1.json`（SHA `a8114fdbe5eaa29bd049658dd22843e099a3ec5e749e5206b1adb6a71b41e133`）、
`source-675534d-2026-the-stage-safari-v1.json`（SHA `91c9f94a8713b4a914304880400683fe7300fc84e91bf7cb1ae70fc76e9b5598`）、
`source-a639100-2026-the-stage-safari-v1.json`（SHA `6d90cc24bc7d0156b9779cc03ea42f5462c465d1aa039e3ff7b8872eed98e3a2`），各附实际完整页面截图。

第三次加入8个只记数值的阶段标记，上限30条；原guard、await、调度、完整就绪检查及实际源均精确逆向核对。
这次记录表明 registry 验证后到资产预热加载完成约2339ms，后续还存在作者脚本与 native 初始化开销；
这不是其中某个摘要函数的CPU耗时，下一步需要结合实际调用代码定位。
Fine的单卡结构审计另发现12,442个无whole元数据的根仍先扫描fine chunks。
`ac3be0b` 将首次探测限制为 sentence 元数据；空 whole 仍按原规则返回，只有非空根再查询原完整 chunk 集。
原 malformed 计数、Set 顺序、拥有者检查、动态 refresh 与 dispose 保持，四个原／prepared 模块完整逆验通过。
真实 Fine IIFE 的15项合同、4项实际调用点守卫及9个相关 unittest 通过，实际接线独立复核后本地提交。
第四次原始报告 `source-ac3be0b-2026-the-stage-safari-v1.json` 的 SHA 为
`5437208533afd2ca4c183114ad6fb16ef3166f5f4a9baa127fce70e166e1b7c2`，截图为 `source-ac3be0b-2026-the-complete-ui-v1.png`。
该次从 connected 到 fine-installed 为6100ms，但没有 Fine 开始标记，不能当作纯 Fine 耗时；
native-ready 到 fullready 为3432ms，前一次仅531ms，不能用总耗时差单独归因或声称稳定收益。
Fine 已接入共同源，仍仅用于隔离页面，本次20.730秒未通过速度验收。
最大卡仍远超秒开目标，以上新源码未推广，也不能沿用v25安装报告冒充本轮新增模板的安装验收。

## Slim 资产校验实测：有改善，仍未秒开

`6534cbe` 仅在已验证的两个原模块 pin 下，把 Slim `load` 已有的 expected-SHA 比较接入原已审 `knownPinMatches`。
FRAME 在已验资源与存活检查之后，临时提供私有捕获函数，仅同步执行时存在；模块捕获的校验器不绑定某次卡片 token，跨卡缓存沿用。
冲突／缺桥／未知模块保持原路径；精确边界漂移拒绝。稳定 descriptor 快照隔离调用方挂起后的修改，防止坏 pin 被改成好 pin 后通过。
原字典校验、packed 解码、32MiB LRU、并发 pending、失败清理、异步 DOM 存活检查及完整就绪门均保留。
15项真实 Slim／桥接／实际调用点合同、四份完整原／prepared 模块逆验及9项相关 Python 检查通过；候选与实际接线分别完成独立复核。

2026 最大卡本次 registry-checked 到 warm-assets-loaded 从上一样本2361ms降到27ms，整个首次完整背面15421ms。
这两个阶段包含加载、UTF8及缓存等工作，不能把总耗时差全部写成 SHA 的独立收益。
原始报告 `source-6534cbe-2026-the-stage-safari-v1.json` SHA
`987f1e917aad918da3b8e5aca429e93d2253d212391dad619b332b710bae20a2`，截图 `source-6534cbe-2026-the-complete-ui-v1.png`。

相同源码在2027真实书籍配置下，`more` 首次正面1694ms、首次完整背面2730ms，688次词频／626条例句核对正常。
其资产预热加载阶段7ms，后续固定 metadata 预热阶段805ms；此处仍有独立慢摘要比较，下一候选尚未接入。
报告 `source-6534cbe-2027-more-stage-safari-v1.json` SHA
`4638cf2b970c75583163debd87bf022f6aa98010ca8a4b58e1377bea7dfedecd`，截图 `source-6534cbe-2027-more-complete-ui-v1.png`。
本次 source HOST 为 `aed67c9c…`、FRAME 为 `1189b0c9…`、HTML 为 `e83af760…`；仅增加两个独立 QA 文件，没有修改正式 index、服务、PG或APKG。

另一个 Cigen 成员缓存试验已停止：真实微任务负例中，吞取 observer 记录后人工调度使最终字体签名停在14px，而原函数为18px。
即便几何调用次数相同也不等价；该候选未接入产品，不能列为已通过优化。

## 共同源206edcc与三个原入口

`206edcc` 进一步把 Bank 固定1,717,850字节 metadata 的原 SIDE_SHA 比较接入同一校验器，仍先同步序列化、验证完全相同的 bytes，再解析该快照。
原 indexes 并发／成功／失败缓存、632项 binding 的后续校验，以及 English 实际摘要缓存和异步存活规则保持；没有用模块 SHA 替代这项独立验证。
11项真实 Bank 合同、15项 Slim 合同、四份完整源码正逆核对和6项相关 Python 检查通过，候选及实际接线分别独立复核。
复核还用真实 metadata 和未改的已审校验器做正负验证，原文通过、篡改在原 SHA 错误处拒绝；未用小测试的替代 pin 冒充真数据。

| 样本 | 首次正面 | 首次完整背面 | 实际显示 |
|---|---:|---:|---|
| 2026 `the` | 2100ms | 16793ms | 9466次／5794条例句 |
| 2027 `more` | 1290ms | 1910ms | 688次／626条例句 |
| 刘晓艳2027 `social` | 996ms | 338ms | 215次／216条例句 |

这是同一实际源、相同完整内容与就绪门的隔离 Safari 单次样本，保留现有缓存，非绘制完成或稳定上限。
2026卡 projection-prepared 到 warm 为80ms，前一源样本为816ms；总耗时仍受后续阶段波动影响，不能声称每次都缩短同样时长。
新增的两个只记数值标记区分了原作者循环和 batch 收尾：该次循环3630ms，随后收尾到 authored_at 为1321ms；
它们不证明纯JS CPU或纯布局耗时，原完整执行顺序、异常、finally及等待门保持，名义29行／上限30行。
三卡汇总 `source-206edcc-three-functional-ui-v1.json` SHA
`7f510edaf42e002d15ee525399d90d1224b9a94b20429afa5713dff72d0ec231`，其中绑定三份原始计时报告及实际完整背面截图。

干净 wheel→仓库外 target 的 v26 核验覆盖144个包文件、6个新增模板、25项MathJax资源和SOURCE、共同LAN模板、实际target导入及两个CLI；4个进程均先禁用PG连接，连接尝试为0。
报告 `wheel-current-install-qa-v26.json` SHA
`348942d660d98886b141719f0e9c0b8527c1c3f4c3ad959691190026028fa9dc`，精确绑定源码206edcc，不能延伸为未来新源码的安装验收。

这批已验证的改进已推广到三个原 index，AppSupport阶段为 `host-upgrades/native-integrity-originals-v5`。
计划 SHA `d16b54f786c7488edcdc7f80ab7293adb22c82a40124581347cf6fd2c3fc7eb7`，安装器 SHA
`141a6a030da82a6119d357f499f8c90ddd3bd90d5ef05cb526dbe8e8e393e41f`。
独立复核确认仅三 index 的 sharedFrame.html 变化，原HOST、COMPLETE、全部数据／资源绑定保留；逐次CAS、完整stat和归属回滚仍与已审v4一致。
实际 apply 完成，随后只读核对三份计划后像、journal写入stat和CAS归属、每书8项源记录及19项源码冻结；真实LAN identity/gzip解压与当前index一致，canonical EA3及SRI保持。
回读报告 `original-index-rollout-v5-post-http-v1.json` SHA
`8e6ad358b3bd57651752a094078d8f2ebb66d4ec562ce5739315f65b581a618b`。
原网址正常点击 `more` 的背面另实际确认688次／626条例句，记录 `original-index-rollout-v5-more-ui-v1.json`；该次正常点击未计冷翻面耗时。
回滚使用同阶段 `installer.py rollback`，只撤回仍属于本轮的写入，不覆盖后续外部修改；将来Git HEAD变化也不阻止归属回滚。
本轮没有改服务、PG、APKG或媒体，没有发布远端。最大卡首次完整背面仍未达到秒开，目标尚未完成。

另一个延后Cigen几何的试验同样未采用：在无IntersectionObserver的原支持回退、小型真实native合同中，
延后高度变化导致一次必要的nearby请求不发生，完成视图少一条例句，即使native ready、最终门和child高度均相同。
负例 `study-cigen-async-hold-prototype-20261017-44y9685f/result.json` SHA
`0fc0d3bbad070b03cf43535c986d8770671c87bf6c539b8da797bc741b30af69`。
这是受控小DOM和合法child消息的反例，不是声称本轮Safari已丢句；候选在接入前停止，原产品几何规则未改。

## 关闭软件后的复测与共同扫描候选

用户确认已关闭不用的软件后，在同一电脑 Safari、同一局域网和原有缓存下重新打开独立测试页。
当前正式实现仍为 `206edcc`。本地候选 `c7f417e` 只把两种已验证旧作者源码的压缩class候选扫描统一；
原逐节点映射回调、作者执行顺序、完整就绪门槛和9d编号路径保留。未知源码不变，已知边界漂移拒绝。
继承属性或转换钩子不能安全判断时保留原全扫描；标准原生函数文本兼容已实录的V8与Safari两种精确格式。

实际Safari的小探针先发现旧候选因原生函数文本换行而走回退；修正后的探针确认走FAST且没有错误。
原始记录 `compact-intrinsics-v3-safari-stock.json` SHA
`1df96507f53a4d1e3ecabb01c7c3ad81e06bba5b2735c1e580a741ba79027f81`。
6项定向Python测试（包含33项Node行为合同）通过，独立复核未发现P1/P2；完整FRAME可精确逆回206的原FRAME。
这是代码与行为证据，不是速度验收。

| 源码／卡片 | 首次完整正面 | 立即请求完整背面 |
|---|---:|---:|
| 206，2026 the | 2530ms | 14065ms |
| c7f417e候选，2026 the | 2613ms | 12001ms |
| 206，2027 more，第一次 | 1271ms | 1856ms |
| c7f417e候选，2027 more，第一次 | 1787ms | 3115ms |
| 206，2027 more，再次独立打开 | 1932ms | 2614ms |
| c7f417e候选，2027 more，再次独立打开 | 1706ms | 2260ms |

`the` 单次背面差约2秒，但不能把这一次差值全部归因于扫描改动；`more` 两组对照方向相反，
尚不能确认稳定收益。第一次more候选较慢的主要差异发生在执行作者脚本前的解码阶段。
所有时间仍是首次完整提交加可用翻面控件的浏览器信号，不是绘制时间、稳定上限或冷缓存承诺。
测量时没有并行运行本轮构建／测试作业；没有清空缓存或修改浏览器保护设置。

实际页面保留 `the` 9466次／5794条例句、`more` 688次／626条例句；the手动返回正面再翻回背面成功，
这次手动重复翻面未另外计时。原始结果与完整说明汇总为
`compact-v3-actual-safari-summary-v1.json` SHA
`d34624297385c1c65d0637fc3f6fb5f055fa7921dfa06df2e9bb84c46078a8af`，并保存两张原生截图。
实测页明确记录基于64f37fd的工作树冻结，实测materialize源码SHA
`af0df4de6d65142a6d5529f2f561c7c994c8ce5fd313e0b8ea0d7be9e7dfde9b`
与随后c7f417e提交相同，不将未提交状态冒称为原64f37fd的内容。

候选FRAME SHA `84198fc2a3569e99d4db02caa93ec15d843e92697ea2b9fbaf1ee41bd254b552`，
HTML SHA `bf84f6f7c5b32c5666306db975c19deb686565e5e036a15f72cca2e679dc691f`。
当前仅新增独占QA文件，三个正式index、HOST、COMPLETE、服务、PG、APKG、媒体和真实Anki均未改。
本地检查点不等于采用或发行；v26安装核验只覆盖此前206，未延伸到本次新增模板。
**首次全部秒开的目标仍未完成，继续处理最大卡正文初始化的剩余开销。**

同一c7源码的作者执行诊断另测得首次完整背面13.752秒；这是含不同有限时钟的另一次样本，
不能把此前12.001秒当作稳定上限。12次真实作者execute中，9d连续编号脚本首次执行2586ms、
9014主脚本两次为397／295ms，batch循环结束后的收尾为917ms。
9d这段包含节点查询、读取样式和编号写入；当前还不能把2586ms全部归为编号计算或样式重算。
原始记录 `c7f417e-2026-the-author-execute-safari-v1.json` SHA
`d235dd4e25b7d77c9c512cdf9879c6dd5d1bb3e65a3a4209fc141e0b66a09160`。
后续先区分首次样式读取与其余循环成本，连续编号规则与正式入口均保持。

## 首次样式读取与组合候选复测

进一步只对编号刷新作有限聚合计时。首份诊断在三个刷新均完成后收到后续源码错误信号，
但旧收集器未保留产品已发出的message/stack，不能把这个信号归因于编号模块，也不能视为完整背面验收。
在仅补齐有界错误详情、仅终态更新诊断面板的另一个独立页面中，错误未再次出现：
完整背面11482ms，首次刷新1918ms，5794次样式读取合计1824ms，其中第一次为1820ms；
后两次刷新39／44ms。原失败样本为首次刷新2494ms、第一次样式读取2368ms。
因此初次刷新主要在等待首次样式计算，而非遍历或计算序号；没有据此绕过样式、编号或完整就绪条件。
错误详情报告 `c7f417e-2026-the-numbering-error-detail-safari-v1.json` SHA
`64f5ba119e630cf4101884129e4dbd0cff530f7ddffe0be485ba1bb034755229`。
单次不复现不等于已定位或修复此前错误。

两项候选在隔离目录组合验证：压缩标记使用具体class候选，并在自定义元素、未知构造器或最近卡片元素不满足条件时回原全扫描；
倒计时只在相同自有state、style、Text、sheet、disabled、有序CSS规则和MediaList均未变化时省去重复写入。
后者的textContent-only及CSSOM media反例先失败、收紧后通过；18项合同与压缩候选新增4项合同独立复核通过。
这是已知模板及标准DOM/CSSOM范围内的行为证据，不主张任意外部修改原生API或公开state后的泛化等价。

| 组合候选 | 首次完整正面 | 立即请求完整背面 | 页面观察 |
|---|---:|---:|---|
| 2026 the | 1878ms | 12489ms | 9466次，目录5794条例句，完整背面控件可用 |
| 2027 more | 990ms | 1893ms | 688次，目录626条例句，手动往返翻面正常 |

计时仍采用相同29处有限数值标记、原完整就绪门和现有缓存，无并行本轮构建／测试。
the作者循环结束到收尾标记为96ms，旧c7另一轮样本为917ms；这是阶段样本差异，
组合中还改变了扫描规则，不能把全部差值单独归因于倒计时，也不能据此声称总耗时稳定改善。
后续native初始化仍占主要等待；没有把这些等待移到可见的半张卡之后。

两个计时原始报告、UI观察范围和两张原生截图绑定在
`compact-v5-countdown-actual-safari-summary-v1.json` SHA
`58e8247b75474847afbc0293faa5cd6779e6d727c430beb86fb152f9a71c3ebb`。
组合FRAME SHA `eec731def65a7bc76bdfb31c06ed9026bc5ac84826783ef81d4b4106b21982ce`，
是c7加两个冻结候选的隔离产物，捕获时未集成仓库，不能冒称原c7源码。
独立stock探针已确认同一v5 helper在真实Safari走FAST；报告 `compact-intrinsics-v5-safari-stock.json` SHA
`8894988c395a6117825aab74b9537c75f5bea9904d946bcaefc66997d74f7e7e`。
该小探针不代表整张卡逐节点路径或速度验收。

结论：**仍未达到首次全部秒开，组合候选未推广，倒计时改动未采用。**
本轮只独占新增QA页面；正式index、HOST、COMPLETE、PG、APKG、媒体、服务和学习记录没有作本轮变更。
后续继续处理完整正文及native初始化成本；本地压缩扫描还需保留已复现CE负例的修正。

本地共同源码随后仅纳入v5压缩扫描的安全回退，未纳入倒计时候选。
旧c7的真实CE class回调会给后面的普通节点添加别名，原全扫描会处理它，缩小候选后可能漏掉；
新增回归先在旧c7失败，再由v5在映射前回全扫描而通过。
6项定向Python检查（含40项Node合同）通过，完整模板替换可精确逆回原c7 FRAME，历史静态封印未变。
测试中的jsdom构造器文本oracle仅属测试设施，没有写入产品；实际Safari资格另有上述独立stock记录。
当前本地FRAME SHA `352c11a45d6ddca81b02cc2b9bb731aa85dafd2c14b57bd94360ce08ddb679ba`，
HTML SHA `91151c540e6182ff422598a32089864ec31d27853b2799e2a7199c2230892871`。
这份无倒计时的本地源码尚未单独做整卡Safari性能验收，不能借用组合候选的时间作为其成绩；
正式入口继续采用206，v26干净安装证据也仅覆盖此前206。

## Cigen现有读操作的聚合实测

在b70共同源码中只对已有的Cigen布局读操作增加有限数值时钟，保持原29处阶段标记。
短路求值、原几何／样式／属性读写顺序、公共refresh参数忽略规则、resize回调身份及异常／batch finally经小合同对照一致。
五个固定原因桶只在首次背面请求期间汇总本轮预备页面的内存数值；MO仅读records.length，没有遍历记录或新增观察器／几何读取。
诊断只在终态显示并本地下载，没有改正式入口。

该次Safari完整背面13924ms，主要聚合值如下：

| 原调用来源 | refresh累计 | 其中layout累计 | layout首次width累计 | 签名结果 |
|---|---:|---:|---:|---|
| MO，9次／111284条记录 | 521ms | 464ms | 423ms | 6次均未变 |
| 作者batch，5次，4次延后 | 1017ms | 970ms | 960ms | 1次改变 |
| load | 不经refresh | 22ms | 0ms | 1次改变 |
| RO | 不经refresh | 14ms | 0ms | 2次未变 |
| public／resize合桶 | 33ms | 13ms | 1ms | 2次未变 |

layout已包含在refresh中，不能重复相加。样式与几何读取可能结算之前积累的布局工作，
这些数值不是独立纯CPU成本；当前记录也不把公共refresh和resize强拆为不同回调。
MO触发的检查有可省空间，但不足以解释整个13.9秒等待；不依据阶段间隔把数秒都归因于MO，
也不泛化过滤原native变更或改变初次／load／RO几何时机。
实际页面背面控件可用，词频9466次和目录5794条例句可见；这是该卡的观察范围，不替代全量内容核验。
原始报告 `b70e707-2026-the-cigen-aggregate-safari-v1.json` SHA
`f27783957e054b9046dc2a3bcac4321a81e51b27b6f39e45e47943a80b48faa9`。
该次含不同有界诊断时钟的独立样本，不能单凭13.924秒与此前12.489秒的差值判断回归。

## 删除Group未消费的全文拼接

完整Group IIFE的私有textView先收集Text节点和UTF-16 offsets，随后额外读取el.textContent放入text字段。
三个消费者只用nodes及ranges适配添加的root，没有读取该text字段；实际分组key所需的其他textContent读取保持原样。
共同源码只在已有ranges适配的唯一返回值中移除该字段，没有增加新的运行时模块、缓存或调用协议。
旧路径的小型真实Group合同记录10次无用全文读取并失败，删除后为0；8项定向Python检查包含6项真实Group合同，
覆盖嵌套chunk、不同义项／graph、目标与审核并集、筛年、后增成员、重复refresh、dispose身份及TreeWalker异常。
四份完整raw/prepared源码核过原pin，并精确逆回；旧兼容／静态历史／压缩扫描封印通过限定逆验保留。
候选及实际差异分别复核；这不是人为覆写DOM getter副作用的等价承诺。

当前FRAME SHA `c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02`，
HTML SHA `8b6e59ff2457dc7cd2cfefbe46d81404dc55ce8c2dd941b040a7ac5ac9de1710`，
materialize源码SHA `caf263d17768d63a0f3fc01813f8204b8b44b23f63414b6ab69f273692177b3d`。
捕获时基于b70的未提交工作树，QA明确记录working_tree=true、commit_contains_all_changes=false，
不能把此字段删除冒称为原b70的内容。仅保留原29处有限阶段时钟，没有附带Cigen或倒计时诊断。

Safari该次首次正面1998ms，立即请求完整背面11540ms；Bank-ready至Group-installed为1240ms。
此前另一份b70聚合诊断为1516ms，但诊断时钟、相邻阶段及环境仍有差别，不能把约276ms差值全部归因于这一个字段，
更不能把13.924秒与11.540秒总差值称为已确认的稳定收益。
原始计时 `group-unused-text-2026-the-stage-safari-v1.json` SHA
`fe5f6edfee9c42f5b45d7d03581faa9ca2e77b452bb835c7534ac7128af47916`。

实际展开该卡“足够，恰好”义项，20次出现展示19条原文；筛2022年，3次出现展示2条原文。
合并的Harlan Coben句子保留双语、目标标记，两份不同依据均可展开；全卡9466次和目录5794条例句保持。
交互记录 `group-unused-text-2026-the-ui-v1.json` 及展开截图按实际范围保存，没有重验音频或手机。
正式入口、PG、APKG、媒体、服务和学习记录没有本轮变更；**首次全部秒开目标仍未完成**。

另外对SHA核实的真实the背面作流式静态计数：44,166,454字符、426,000个序列化元素；
关闭details区间去重占50.99%，主要是14个sf-sense正文块（241,836个后代元素），具名history仅占3.13%。
此前staticHistoryEligible=0的直接原因是现白名单的三类根均不存在，不是ID或compact标记拒绝。
32个source-confirmation审核块只含320个后代元素；即使另作安全扩展，也不能把它们当作DOM大头。
报告 `the-static-history-pool-20261017.json` SHA
`603e3c0440110695b536a82da7b896019d732aca659777d5410ebb2cb530530a`；
这是HTMLParser的序列化输入计数，不是HTML5修复后的真实DOM或性能归因。

后续更大的优化只先做最小可逆状态验证：构建时计算确定变更，运行时绑定原始节点并恢复真实私有状态，
保留source／metadata／范围校验与refresh、筛年、dispose规则；最终HTML加SHA不能替代WeakMap、原Text对象和undo日志。
当前仅评估Fine的小卡原型，尚未接入产品或取得速度结论，不以假ready或隐藏可见内容绕过完整门。

## Fine编译计划的隔离验证与停止条件

第一版只在一个完整小DOM fixture中验证状态恢复。构建时调用同一Fine install记录语义计算，
运行时核调用方持有的外部SHA、原模块／来源／metadata绑定、完整before快照和操作覆盖，再进入原闭包Map及handle。
这是显式的新信任边界：语义判断移到构建时，不能声称运行时仍独立重复了这些判断。
8项局部合同通过，覆盖active先清理再remember、原来不恢复的active不额外恢复、条件式dispose、Text／元素身份、
后增内容refresh、原observer、取消及损坏计划无写拒绝。十处记录hook可精确逆回6627字节的原Fine IIFE。

独立复核没有发现新增P1／P2，但**v1不接入真实大卡**：25节点的小fixture原完整document为821字节，
plan为5845字节；before／after分别2106／2021字节。这个比例不能外推真实卡，
却已证明主体是无条件双份全页快照，运行时还要遍历、建Map、复制属性及多次JSON比较，可能抵销Fine分析的节省。
其调用方mutable版本对象亦未防await期间变化，故封印状态明确为not-installable。
原型及合同封存于本地`output/study-catalog-20261015/fine-compiled-protocol-v1/`，manifest SHA
`d02345bd767603ca6e6f47b5a7f81b4e171a61b39b6561a8e8df824e010b7521`，没有产品或Safari性能通过结论。

真实小卡的只读定位选2027 abolish：4条例句、39199字节背面，其中一个原文同时有whole与fine标记。
active Slim的Fine调用在已验证raw／index载入之后、Projection prepare之前；它不同于前面的deprecated hydrate。
此前倒计时、绝对base、child token和可能的iframe高度已经变化，不能假定整document跨次快照相等，
也不能为匹配而删除时间内容或关闭原逻辑。源定位报告SHA
`c7642ee9e59eeeae87288c6729aedf515fe4e909a62e3792953cc32a4e2ae9a2`。
下一版只评估Fine实际消费的完整语义输入图；它不读／不替换Text，原全文证明仍由统一来源校验承担。
必须先独立复核，再走真实小卡共同pipeline的捕获／另次重放；小DOM通过不等于真实卡、构建时producer或秒开通过。

后续v2用一次相关成员查询记录有序root／chunk／mark／history祖先图、完整相关class和原IDs，
after仅保存属性delta；相同小fixture的plan由5845降为3306字节，但没有成本优势结论。
独立复核实际复现一个P2：无own的Window状态被当成absent，而原Fine会读取继承状态并清理active。
修正版在写入前以descriptor-only检查保守拒绝继承／非枚举消费字段，保留普通install，
两个负例在旧v2先失败，再与原12项一起14／14通过；定向独立复核确认阻断该P2。
旧v2封印未覆盖，修正版manifest为`e55df66bc2edefe69ad22565da3242b7534efc0b650ff96b92bbe5b7d1dd325e`。

Safari真实abolish捕获A已通过原统一pipeline和完整门：首次正面1330ms，立即完整背面314ms，
其中Fine构建记录段2ms。该阶段含新增构建记录工作，未作为普通路径性能基线或提速成绩。
物理词频仍4次；完整DOM中8个root分属两组4条原文，不能把DOM副本数改报为8次。
初始Fine统计为rootsWithWhole=2、filteredSpans=42、wholeOnlySpans=22、malformedMetadata=0；
图140成员、106操作、42记录／delta，精确transcript为31718字节。
外部冻结SHA `f65c64793eb5bf1a6d56eb01936b0305982adf5a13650f2b8796892a1aca6470`，
本地报告SHA `f8cf9998f43e546ac4d8cacce9c9ec82af6ce1acf243dc1e34556457e33a7728`。
聚焦全文／标记读取和报告序列化均在完整门计时之后；正文与transcript只本地下载，没有GET回传。
这次是运行时辅助捕获；**A记录本身不证明另次重放、构建时producer、大卡收益或产品接入**。

随后在另一个新Safari页面完成重放B，外置预期SHA保持上述精确原串，没有重新声明自己的锚。
原统一pipeline、来源／metadata／范围校验和完整门继续执行。首次正面1230ms、完整背面438ms，
hydrate段16ms；这些与A的构建记录段包含不同工作，没有净提速证明，不能把小卡时间推广到大卡。
八个最终原文root的完整HTML、文本、chunk IDs／class、初始及最终Fine统计与A逐项全同，物理词频仍4次。
实际展开为4条原文，选2007年为2条；点击Bolivar句中的abolish，英文abolish slavery与中文“废除奴隶制”细块同时高亮。
往返翻面后2007年筛选与2条原文保留。未重测音频、手机或异步换卡UI。

B新增await调用先核alive，失效时dispose已返回handle，活跃时才keep；不能直接keep(await hydrate())，
原keep自身不检查归属。该调用的active／stale／reject三个局部合同通过，不把它当成实际换卡验收。
两个checker分支的真实完整模块接线均逐步逆回原6a模块，FRAME／HTML精确逆回共同61b／正式index。
真实小卡汇总`fine-v2-real-small-safari-acceptance-v1.json` SHA
`267c708f82a1be3e4317dd828c0ee82a14c5acfde0586cdeb7fdb931dc457e7b`；
B原始报告SHA `82635f699a34f2757c617df3d5a6daf6867cd0fe3cad28e962d415b9f7fd90a5`。
两个自建QA标签页均已关闭，三个正式入口、PG、APKG、媒体和学习记录未改变。
固定协议及14个合同另存入`tests/fixtures/experimental-fine-plan-v2/`，迁入后重跑14／14通过，
没有把实验代码接入运行时。当前已证明的是这个Fine状态恢复方案在真实小卡可重放，
下一步只应先评估大卡的输入图／摘要／操作重放净开销；**首次全部秒开、构建时producer与产品采用仍未通过**。

同时只读排除了“暂存关闭sf-sense正文，等native ready后只放回就提交”的捷径。
实际Projection.pairs、Bank、Group均消费这些正文：Projection prepare只验JSON，不能替代当前DOM标注与范围验证；
Group面对空panel还可能写零行。shared-v2已关闭这些native observer的自动刷新，放回不会自行补处理。
必须在消费者前还原，或放回后完整补处理并重新确认完成，不能仅靠现有整体ready门证明逐例已处理。
本项只是固定源码依赖判断，没有扩大暂存白名单或实施延迟显示。

## Fine大卡重放净成本：不采用

基于afcb4dc的同一共同源码，在真实Safari另测2026 `the`。捕获A通过原完整门，首次正面1940ms、
立即请求完整背面15999ms，Fine构建记录2877ms。此轮含额外记录，不能以它替代此前普通61b单次11540ms，
也不能把两个历史样本之差称为稳定性能收益。Fine初末统计一致：2894 rootsWithWhole、64085 filteredSpans、
35167 wholeOnlySpans、0 malformedMetadata；这不是全卡最终DOM／交互的新增验收。

真实计划为62,463,885字节，289611个before成员、194510项操作、64085份record及delta。
原串SHA `6c126be2530ee80e351add687bcbf449f2981c5c181e74c1e2a62e7f00f7a579`，
同字节gzip为2,769,162字节，SHA `42bcc4063d0d738f323b879a03e38ee3564b350b2cf9f71204ff0b0913c36e1a`。
两个新页分别使用外置原串B和gzip B2；没有把大串多层嵌入FRAME／module／HTML，
GET200、no-store、完整文本、SHA与hydrate均在同一操作和背面计时内，gzip解压也计入B2，未做未计时预取。

| 隔离轮次 | 首次正面 | 完整背面 | 观察结果 |
| --- | ---: | --- | --- |
| A，同原算法捕获 | 1940ms | 15999ms | 完整门通过；含额外compile记录 |
| B，外置原始JSON | 1880ms | 未取得提交 | 原10秒门超时，native仍preparing |
| B2，外置gzip | 2422ms | 未取得提交 | 原10秒门超时，native仍preparing |

B/B2的Fine collector只在操作完成后记统计；not-called表示没有完成观测，不能据此断言没有进入hydrate，
也不能把超时误报为一个测得的完整背面时长。数字是页面提交／错误信号，不是CUA工具耗时或绘制完成。
原29处时钟、全部来源／metadata／范围校验、完整门和10秒限额保持，没有用假ready、加长超时或半张卡掩盖失败。
本轮只证明当前v2没有通过这张大卡的采用门，不能从失败定位出一个尚未测完的细分耗时。

定向独立复核在B发现诊断P2：collector超时删sink后，尚在执行的有效native流程可能因直接调用sink而失败。
B2将这一个观察调用改为可选并隔离异常，fetch／解压／文本／hydrate／来源错误仍照原样抛出。
实际调用切片的missing-sink、throwing-sink与原运输／取消／拒绝共12项合同通过；
真实Response/DecompressionStream把gzip逐字还原到原SHA。两checker完整模块、FRAME／HTML逆验及两文件独占安装／
owned回滚合同通过。复核确认该P2关闭，没有把这些局部合同当成真实大卡通过。

原始报告分别为`fine-v2-the-2026-capture-a-safari-v1.json`（SHA `f6158a6149c4d0afe9e9ba57ccc7f9a79036759df3fe3677e755b4289fde998d`）、
`fine-v2-the-2026-replay-b-safari-v1.json`（SHA `d5c556d4cf1dab11164d3157d4cad69bdccc24b35c0a22d6650f459cf3c26545`）、
`fine-v2-the-2026-replay-b2-safari-v1.json`（SHA `9029662fa5546bc614d2408cccca3908e035651415c05cc9a42479c92b70425f`）。
决策摘要`fine-v2-large-net-cost-decision-v1.json` SHA
`1d1f97b31fce68dd70a9d9653f6ac71ad6d85db862dd78483f91dca3e7e5bc8c`，较小的构建／逆验／合同文件另存本地`fine-v2-large-net-cost-v1/`。
大串、真实卡和原始报告留在本地output，不入Git。三个自建QA标签页已关闭，三个正式index逐字复核未改；
产品共同源码、PG、APKG、媒体、学习记录、LAN校验脚本及服务保持。

**决定停止v2大卡采用，不继续扩大运输协议或超时。首次全部秒开仍未解决。**
另一个只读定位修正了编号依赖的适用范围：真实the正反面没有as-manifest，所以它的Slim选载slot集合为空；
通用materialize仍会保留关闭detail的非空manifest，且discover从at:0开始，不能推广为所有卡都已加载完成。
后续编号排版候选只能先限严格已验作者、slotless及无旧编号observer的fresh realm，在原完整门前完成编号；
取消／晚期资格漂移须拒绝当前准备，Cigen布局与完整门不变。这是待验的隔离候选，不是已实施的提速。

## 编号延期的后续实测与新生成计划

slotless/fresh候选经定向复核发现P2：原可通过的隐藏或旧子帧错误，被新等待扩大为失败。
原版两例通过、旧候选两例失败；修订只等待本次native状态／归属／取消／原期限，子帧仍交原完整门。
修后15项小合同及定向复核通过，唯一helper逆回旧候选，再完整逆回c7 FRAME／8b HTML；没有接入共同产品源码。
新候选FRAME为`5cac72298889bff08a35e0457631ac243e14ce6f4de6e3f18c960ad6ed1fe467`。

真实Safari的the完整正面1975ms、立即请求完整背面10970ms；两条数值标量确认实际延期并完成两次canonical编号调用。
enqueue／flush时间包含其他工作和等待，不能当作编号函数自身耗时。原完整门、10秒门及canonical Fine原路保持。
页面仍为9466次、目录5794条例句；未再次全DOM／交互验收，单次对比历史11.540秒没有稳定净收益证明。
原始报告SHA `77bd98a1c365504df8b0312eae0b22c381fca98820f3934dd969cef28e678df3`；
决策`numbering-deferred-slotless-v2-decision-v1.json` SHA
`0329ab9fac3c9c7799491659d3260ef0a6f150bfbdcb393478438640f1bc0bc6`。
三个正式入口与产品／数据库／包／学习记录保持，隔离标签页已关闭。**该候选未采用，目标仍未完成。**

原生查找另用独立file:小样例实测：关闭details唯一词命中1次并自动展开；template未插入0次，插入后1次；
until-found唯一词命中1次且可见，未读取完整beforematch日志，不外推HTTP／真实卡／手机或性能。
该事实排除了直接把闭合正文搬入未插入template并声称查找等价的捷径。
后续按[显式新profile计划](STUDY_COMPILED_PANEL_PLAN_20261017.md)，将可确定的语义处理移到生成阶段，
新runtime明确绑定自己的交互状态，不伪造旧WeakMap，不先改变闭合正文查找行为；完整小卡交互及最大卡净成本都需另证。
