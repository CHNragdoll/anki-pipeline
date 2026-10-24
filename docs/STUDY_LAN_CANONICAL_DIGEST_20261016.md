# 局域网入口仍发送旧校验脚本：统一接线修复

当前页面与包内脚本并非同一条运行路径。2026-10-16 的实际 HTTP 读取发现，
`192.168.3.5:8771` 的代理仍注入旧 `scripts/lan_sha256.js`；
`127.0.0.1:8771` 是独立的书架后端，不经过这段注入，不能替代真实局域网入口验证。

## 当前证据与源码修改

| 项目 | 修改前实际响应 | 共同模板 |
|---|---|---|
| 路径 | `/_preview_lan_sha256.js` → `scripts/lan_sha256.js` | `anki_pipeline/templates/lan-sha256.js` |
| 字节 | 6,404 | 13,757 |
| SHA-256 | `5e4026b6f4d092924ef92ef8552882815df43614efa70a8bd6e20904f3a91075` | `ea3c80d4b145e8cf1673cbf9be0af7249497f0d98c75cb0d48f896da16e109e6` |
| 实现 | 旧同步校验 | 已审计的 fast core 与有界 Worker |

旧网页的 SRI 与旧响应相符，所以校验并未报错，但代理注入的副本不是包内共同实现。
HOST和FRAME本身也嵌入共同实现；正常shared路径中HOST会覆盖无标记的旧副本，FRAME与原生模块bridge再调用顶层digest。
因此这证明接线不一致，不能证明此前实际摘要调用一直使用旧实现，更不能把54秒直接归因于旧代理脚本。

源码节点 `14c968c` 只把代理的 `LAN_HASH_RUNTIME` 和固定 SHA 接到共同模板，
不修改 SHA 算法、BufferSource 快照语义、错误 API、2 Worker／8 作业／64 MiB 限制或本地回退。
实际源码两处设置逆回后与旧源码 SHA
`0a2ca09a2ca27364d6433ec654d9ff32a3b72822979edb2f3396b1a907376c37` 精确相等。

## 回归与边界

新合同先在旧源码下 RED：GET／HEAD 仍返回 6,404 字节且路径指向旧副本。
修改后 5 项定向检查通过，验证实际 handler 返回共同模板原字节、HEAD 长度、注入 SRI，
以及字节被修改时仍返回 503、不转发后端、不泄露修改后的脚本。
原签名卡页与历史正文保持不注入。独立实际 diff 复核无剩余 P1/P2。

源码和隔离 handler 通过不代表已运行进程自动更新。服务重载必须单独固定旧进程身份与参数，
保留备份及有条件回滚；不能重启独立书架后端、修改学习记录或扩大绑定范围。
实际运行状态、同一 Safari 的前后测量及完整目标是否达标，另按执行回执记录。

## 当前实际运行状态

2026-10-16已按外部根封印`6071d581b80bff2f47d411605cef727d64980c6c8b6687eb10415b2e1e13ea4e`执行。
部署助手SHA为`3a35105d81553c7e2c73b9f7063a45b630b4290fa6e81f557b9c32dd11558215`；
17项合同及独立增量审查通过，覆盖已退出/部分监听、PID复用、外来监听、部分写入receipt和并发源码保护。
只替换原代理进程，仍绑定`192.168.3.5`的8765/8771；独立书架后端保持原启动身份。

根线程再次GET两个实际LAN端口，响应均为13757字节、共同模板SHA，HTML注入SRI为
`sha256-6jyA1LFF6M8Wc8v5vgr3JJSX8NmMdcsNSPiW2hbhCeY=`，脚本仍`no-store`。
本机证据`output/study-catalog-20261015/lan-canonical-digest-deployed-v1.json`，
SHA为`5dec34b3ccc14e165c548b32a4bbb5b6b8189c95c724274299e5949540da55c8`。

持久助手、原源码备份、根封印和安装前/启动后/完成回执位于`data/web-study/service/`。
需要回滚时，从本仓库目录对同一持久助手使用`rollback --seal <同一根封印> --seal-sha256 <上述根封印SHA> --apply`；
它只处理回执中归属相符的代理，并以原stat与内容SHA条件恢复源码；后续源码变更或外来监听会拒绝。
回滚代码与失败路径经隔离合同验证，本轮成功安装未为演示而再次中断真实服务。

## Safari结果及尚未完成的性能工作

切换代理前，同字节v20 QA在电脑Safari取得正面提交8890ms、立即请求背面后54349ms。
计时是父页面单调时钟到已有完整提交信号（含消息传递），不是paint；默认不包装digest。
报告`v20-safari-canonical-digest-before-v1.json`的SHA为
`ff7447d553613a6abaaa90879a2ec1b53eb47190190944d48868f307ad4fd12e`。
当时LAN marker=true只能证明共同API已安装，Worker available=true不能证明Worker实际执行成功。
原生读取超时后恢复，取得切换前带观测报告：正面8074ms、背面56195ms，
两份19425775/17177302字节输入的顶层canonical摘要分别32871/32390ms。
SHA为`80cec0d386c2ce81873404334a0efe68fba515967d84ca3366f0698b7ac7bac6`；
前16条观察上限已达到，不能据此否认之后还有其他调用，也不能由API可用断言Worker实际成功。
切换后同一Safari默认不包装digest的结果为正面10393ms、背面68882ms，报告
`v20-safari-canonical-digest-after-v1.json`，SHA为
`4a2be7276ffae86ada10b233556b8a137a253b1b1aced20c0d52ea1a68e08a32`。
本轮没有速度改善证明；两次系统负载/缓存不恒定，不能据此算固定加速或退化比例。
同轮只读系统观察为load约334、交换空间已用58330MB；环境压力与页面成本仍须分别验证。

全量索引排名显示more不是最大数据卡：2026/2027的the完整数据为55603149/47883568字节，
刘晓艳最大social为950245字节。最大字节不等于最慢布局；后续实际Safari验证必须包含这些候选，
并保留普通卡、首次立即翻面和重复翻面的区别。整个性能目标仍未完成。

随后只读复用既有WASM隔离页，在Safari实点完成8次固定输入对照；4.4MB输入fastJS为2185/2666ms，
WASM为442/507ms；1.95MB输入分别1241/1152ms与156/178ms，全部SHA相符。
这是同步计算局部对照，未改生产，也未测Worker回退。原生实拍与逐项人工转录见
`v20-safari-wasm-visual-observations-v1.json`；下一步范围见[隔离候选计划](STUDY_SAFARI_DIGEST_CANDIDATE_20261016.md)。

本机原始证据：`/tmp/study-lan-canonical-digest-20261016/` 的
`http-before.json`、`handler-red.log`、`handler-green.log`、`implementation.json`。
