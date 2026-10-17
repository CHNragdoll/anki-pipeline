# 补齐原审核历史结构，复用已生成正文

真实批次发现三类既有历史不能进入原 e56 的严格资格集合：
原 `.sf-report` 中的 inline history、原 examples 中的 source-confirmation history，
以及原 ownership history 的 inline 详情中封存的双语 DIV。
修正同时覆盖 AST 与 binder，只增加这些由实际来源证明的组合；未知 owner、原生 LI、控件、其他消费者或不符的 graph 仍拒绝。
原 AS/AF 摘要、完整树、来源排除证明、once/current 和插入授权保持；不删除或隐藏审核内容。

新 binder 为 `f703169353965e8d74d2c5a9ef7e2b49be3a99d75cf6be97571304d41fb3c93b`。
旧 e56 仍保留明确准入。`upgrade_delivery_runtime` 对已成功构建结果只调整交付 binder，
保留 HTML、profile 和旧 build record，另记 `runtime_projection`。
网页和 Anki 只接受这两个已知版本；默认 8a/b151 及上一 f6dae transport seal 仍有独立逆校验。

独立 8 个必要定向测试通过，覆盖新历史资格、负例、旧 profile、原生宿主和 seal。
实际 `date`、`belief`、`end` 已通过正常共同构建及实际 HTML/profile 的隔离绑定，invalid 均为 null。
[来源、检查范围和三份实际结果](../output/study-catalog-20261015/compiled-history-coverage-v1/README.md)均保留。

本节点尚不代表三书全量完成、真实客户端通过或新的速度结果。
原批次不重启、不重做成功正文；新增失败项由冻结修正版单独补跑。
