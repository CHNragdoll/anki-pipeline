# 最大卡 compiled gzip transport：实际 A1 → B → A2

本候选没有证明净收益，不推广。这里只归档已有单次 Safari 顺序样本与实现证据，
没有重测、调整时钟、启动服务或改动产品／正式导出／PG／APKG。
A 已经是冻结profile的 compiled 路径；B 仅换三项 compiled 资产的显式gzip传输，
这不是原生算法与 compiled 算法的对照。A/B实际完整内联HOST均为6a96b752…，
aed67…仅为历史正式外部HOST；原wrapper→prepared完整来源链保留。

| 原始运行 | 完整正面 | 正面后请求到完整背面 | 三资产并发区间 | 原完整门区间 |
| --- | ---: | ---: | ---: | ---: |
| A1 | 2044ms | 4464ms | 450ms | 332ms |
| B | 4281ms | 8959ms | 476ms | 3088ms |
| A2 | 2542ms | 6575ms | 881ms | 485ms |

三次均shared、原完整门ready、compiled handle invalid=null；1800groups／4303
分组成员／201Bank，编号能力5794行。这里没有重新做全DOM／全文／Find逐项验收，
原QA里的9466／5794也是既有输入的静态期望，不能改称此次全卡实数扫描。

`observations/{A1,B,A2}.json`保留root下载原字节。`observation-summary.json`
按原performance时钟边界重算相邻阶段，不将并发资源时间相加；author／binder
为inclusive wall，firstGeometry嵌套在refresh／batch内，同样不能相加为总耗时。
B在该顺序样本中比两次A慢，但不能据此单独认定gzip造成回退，亦不是冷缓存、
paint或稳定速度上界。首背仍未达用户性能目标。

B三载体实际GET200：HTML5173180B、profile3003348B、runtime8148B，总8184676B；
没有compiled raw fallback。它们解压后分别对应原49390544B／22459697B／27260B
输入，SHA未变。只保存原路径、字节和pins引用，没有重复拷贝这些大文件或8MB载体。

服务共有172条实际request。除favicon404，还包括同一预测next-card的front gzip
与raw各3次404（A路径各2、B路径各1）。root根据原prepared index确认该邻卡ID
前缀34b80dc…，不是目标the。隔离closure未覆盖该背景预取，因此不能把这次称为
完整全书资源闭包验收或无网络错误的纯净对照；未知路径仍按404拒绝。

`qa/ready-08451e9c7347.json`与`qa/closed-08451e9c7347.json`是完整实际收据。
PID82468已drain，used54sources再SHA全部相等。root报告session41646 exit0、
port49246不再listen、自有QA窗口关闭；归档者没有重新查询进程／端口。
root exec工具输出曾含keep-alive read的ConnectionResetError且被工具截断，
没有事先重定向的stdout/stderr原文件；这里只保留root陈述，不伪造日志，不能
称server errorfree。阶段FROZEN／verification的server_started=false是准备时
历史事实，后续ready／requests／closed和实测JSON说明后来实际运行过，旧文件未改。

候选v2保留完整6dd1封印、精确6处edits、唯一cache-hit修复diff、12＋4合同日志
及两个P2旧RED。源码／QA父页大于100KB者仅作确定性gzip档案存储，解压后逐字匹配
其原SHA；这种归档压缩不是候选传输载体，不改变任何运行逻辑。
`archive-manifest.json`逐项列原路径、原SHA、存储方式和存储SHA。

只读核验（不读外部大资产、不运行Node／服务器／浏览器）：

```sh
python3 output/study-catalog-20261015/compiled-gzip-transport-observed-v1/verify_archive.py
```

如需独立复核原小合同，可用同一脚本的`--extract-candidate /tmp/新的不存在目录`
恢复小代码，再人工运行其中contracts.cjs、cache-hit-contract.cjs；本次归档
没有重跑它们。不要运行历史pack-assets.py，也不要据旧QA构建器重新生成大卡。

根线程另行更新项目README并决定本地Git归档；本任务没有stage／commit／push。
