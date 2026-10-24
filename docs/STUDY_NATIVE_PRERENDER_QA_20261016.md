# 原生正文预生成与浏览器状态绑定：隔离验证

当前正式网页仍为 v18。统一数据库、卡片事实和原 APKG 不在本轮修改范围。
本轮继续解决同一交付目标：选卡及翻面流畅，完整背面一次显示，内容、计数、交互和来源核验保留。
此前静态审核正文暂存样例保真但收益不足，已停止，不混入本方案。

## 要验证的改变

统一生成器在受控 DOM 中执行原生细块投影、阅读标签和同义分组，保存派生显示快照及状态清单。
浏览器仍核对原 source、expanded 内容、registry 和原 `Projection.prepare(data)`，
新增明确的 `installPrerendered` 路径验证快照与原输入的对应关系，采用已生成节点并重建私有状态。
不能直接跳过 install/refresh，也不能把产物摘要当成编译语义正确的证明。

该改变属于生成器及网页派生协议，不需要改变 PostgreSQL 表结构。
不按年份、书名或单词特判；先选择普通 remote 和长卡 more 验证同一个实现。

## 接口及不变项

- 原 prepared artifact/proof 保持不变，派生 DOM 使用独立版本的 receipt，绑定 card、side、
  原 wrapper/payload/side/expanded 摘要、原及 prepared native module 摘要和派生 HTML 摘要。
- 私有 WeakMap、节点引用、事件和 dispose 回调必须在当前 realm 重建。
  清单不是可执行代码，不接受任意选择器、HTML 或跨卡节点来冒充已验证输入。
- projection 保留原文签名、目标/chunk 核验及还原记录；fine 保留原属性基线；
  bank 保留 metadata 与 container 原文绑定；group 保留物理成员和过滤/还原状态。
- 作者脚本执行顺序、词源子页、字体、三个稳定几何样本和原失败处理保持。
  不增加公开可写的摘要种子，不改变现有缓存或预取预算。
- 同一 generation 贯穿异步边界，取消及 A→B→A 不得把旧节点/监听器带入新卡。
  不支持的模块组合沿用原渲染路径，不能静默显示不完整快照。
- 所有完整原文、译文、chunk、target、审核历史和 ID/计数保留；不改为联网点击后补正文。

## 实施和验收

1. 在 `/tmp/study-native-prerender-20261016/` 构建最小原生 API、受控 DOM 构建器和清单。
   在独立 `/tmp/study-native-prerender-host-20261016/` 对接 FRAME 和唯一 QA 入口。
   首先冻结接口，再运行普通卡及 more；不覆盖正式入口和产品资源。
2. 先取得旧 API 不具备快照采用能力的失败检查，再检验新路径：输入/清单错配、
   目标/文本篡改、重复初始化、dispose、取消和跨卡。独立复核实际 diff 和回退语义。
3. 两路径对照正文、主例句、物理次数、chunk/target、group/bank、历史内容及引用。
   more 的 626 条主例句、688 次、578 历史引用，以及既有全文/历史摘要对照不得减少。
4. 实际 UI 验证展开、年份过滤、键盘/点击和切卡，记录首次正面、立即背面及总等待。
   相同条件前后对照，不能把主机负载或缓存变化算成提速。
5. 只有实际收益及保真证据足够，才接入共同源码、全范围回归、三书条件推广、
   干净安装和当前 Safari/设备验收；样例通过不代表完整目标完成。

关键节点保留本地 Git。当前没有远端 push、PR、合并或发行授权。

## 原型结果：校验不足，停止接入

原生原型已写出 29 处精确边界适配、可逆节点状态编码和受控 DOM 构建器，
变换可逆回原模块。普通 remote 的解析、状态绑定、refresh 和 dispose 对照通过，
但它的新增 projection/group/bank 都为 0，不能据此证明性能收益。

实际负例确认了必须停止的原因：同文 `alpha` 在 offset 0/11 对应的两个合法 mapping ID 交换后，
原 `Projection.prepare` 仍通过，原型采用分支也返回 `errors=[]`。
全文签名与合法 ID 集合不能替代原 annotate 的位置/target 语义核验；
fine/group 的基线和恢复状态也不能只信清单。产物摘要不弥补这个缺口。

more 构建在 HTML 重解析后的节点定位报 `Prerendered node identity differs`，
没有得到成功 sidecar 或耗时结果，未重跑。没有把运行于 clone 的完整重放当成提速方案。
Host 侧仅有来源/摘要/取消等 8 项独立 receipt 合同，未连接原生候选、未生成可安装 QA。

因此停止这一采用路径，不改共同产品源码、正式三入口、PG、APKG或媒体。
代码、精确反例和输入封印保存在本机 `output/study-catalog-20261015/native-prerender-rejected-v1/`；
STOP-SEAL SHA 为 `7c779fed2540145270de5bf3a8a73575c942a64784ae80b50e28aaf6c85abf97`。
这些证据只证明原型不应安装，不代表当前正式渲染存在同一问题。
