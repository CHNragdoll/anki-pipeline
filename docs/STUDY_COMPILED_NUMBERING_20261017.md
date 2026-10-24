# 共同生成端先准备显示序号

真实 `train` 的原生隔离回放指出：预生成 Bank 容器保留旧序号 `52`，原作者编号刷新把它改成实际展示中的 `34`。
e56 的完整正文校验因此按预期拒绝 `text node-0000077`。这时两处 AS 历史槽还没请求，不能把它归因为历史正文缺失。

修正在共同生成端完成：执行原四语义处理后，按已接受完整渲染方案的原 `9d154…` 编号规则准备合法 badge，
然后才生成同一份 HTML／profile。网页与 Anki 不分别修改已签资料，也没有跳过 exactText 校验。

## 保留的规则和证明

- 原规则的顺序保持：非历史 `ol.examples`、直接子 `li.example-card`、排除 hidden／历史／computed display none，
  对合格行递增序号，再仅处理该行首个、最近 LI 相同、合法数字的 `.index-tag`。
- 只更新一个原始 Text 节点的数据；非单 Text、未知结构／namespace 或 display 资格均拒绝。
  原文、翻译、审核依据、来源 ID 和物理次数不随序号变化。
- 来源 CSS 必须以 `_study_<完整 SHA>.css` 引用，冻结时重核实际字节。
  生成时按原 link 位置加入临时 style，连同原四模块新建并记录 SHA 的 Group style 进行完整 CSSOM 核验。
  条件样式若可能改变主 LI 的 display 则拒绝；无关的响应式字体、padding 不影响资格。
- 不执行编号作者的启动 IIFE、计时器或 MutationObserver，也不第二次运行原四语义。
  全部检查通过才修改 Text；随后真实 CAS 逆回原 Text，再重新准备并逐项比较证明，临时 CSS 在成功和失败路径均清理。
- `initial-numbering.json` 保留逐项 before／after、两份 SHA、ordinal 和 DOM 路径。
  其完整文件摘要同时绑定于 source-proof、reconciliation 和 producer report，共同资产存储保留证据。
  Python profile 输入器拒绝缺少该证明的原编号来源，原始 source artifact、字段和来源 pin 保留。
- 源 HTML 在 DOMParser 之前检查重复属性；helper 不声称能恢复已被浏览器解析器丢弃的原属性。

## 本次实际观察

| 同一已认证来源 | 合法主 badge | 需要改动 | 逆回再准备 |
|---|---:|---:|---|
| 2027 train | 43 | 29 | 完全一致 |
| 2026 blank | 61 | 0 | 完全一致 |

两个实际构建保持原双语、审核节点、物理身份和源脚本的既有对账。
`train` 新 HTML 为 `7a0394e16a982d6f9376aac8b15315b2638482d3caa02c954039093c2166eb91`，
profile 为 `cd7072679f8890ec16b435b15735c8761c22ea550eff3c6502221a5650633490`。
服务器构建时间约 3.1／3.2 秒；这些数字不是用户点击背面或浏览器绘制时间。

74 项相关生成端检查通过，包括原输入／producer／profile、共同存储／worker 和新增编号小 DOM 合同。
独立复核未发现 P1/P2，原规则、CSSOM 篡改拒绝、CAS 逆变换和部分样式加载失败后的清理均有定向记录。

小体积证据见[本节点归档](../output/study-catalog-20261015/compiled-numbering-v1/README.md)。
完整新包、真实 Anki 客户端、Safari／手机速度和三书全量输出继续分别验收。
本节点未修改 PostgreSQL、真实 Anki 集合、正式网页入口或发行附件。
