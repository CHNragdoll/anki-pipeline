# Safari共同校验实现：隔离候选计划

当前正式v20的首次完整背面仍未通过性能验收。局域网接线已经统一，但同一Safari仍出现54–69秒等待，
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
随后 90 秒超时，尚未到 body 接入。已定位到两 proof 之后、正文接入之前，
不能直接认定是 Projection、bank warm、DOMParser、资源读取或定时调度中的某一项。
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
目前仅准备整卡隔离 QA，尚未用于正式入口；固定输入的能力测试不等于它的整卡验收。
