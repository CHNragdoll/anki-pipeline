# 已选完整背面方案的批量网页接线

`attach_compiled_library(root, catalog, prepared_config, results)` 消费同一共同生成器的结果，
为每卡写一个小 envelope，独立绑定原 prepared artifact；原 artifact、profile 和全部来源摘要不变。
HOST 先验证 front→envelope→原 prepared，再按当前卡片与 wrapper 交给 FRAME。
全局 FRAME 仅保存共同 binder 和交付模式，不把全书正文或每卡 profile 常驻首页。

旧 8a/default HTML 与原 inline A 保持不变。新的传输变体由八处精确补丁产生，并能逆回 8a。
内容生成、e56、完整正文和字体／子页／几何完成检查均沿用已选方案。
来源 header 支持原 17 项以及原历史卡成对增加两项的 19 项，半对或未知字段拒绝。
gzip 载体按实际压缩字节摘要寻址，解压结果仍与原正文摘要核对。
新资源通过持有的 evidence 目录 fd 发布，目录被换成其他目标时拒绝，不写外部目录。

7 项实现检查通过，含真实首批 `radiate`、`save` 的原 prepared/profile/全部绑定核对。
独立复核 6 项通过、1 项实物 opt-in 明确跳过，无剩余 P1/P2。
[小型原始记录](../output/study-catalog-20261015/compiled-web-attachment-v1/README.md)区分合成 fixture、真实源和 GUI 范围。

为先交付已选方案，首批 100 个真实输入（99 词卡、1 原说明卡）已按原 inline A 接回 2027 原入口。
Safari 中实际核对了 `oblige` 完整背面、展开义项的双语原句、连续例句编号和原词源。
此为原 inline 路径的首批交付，不是新 envelope 的全书验收，也没有新的速度保证。
原文、卡片身份、学习状态和原媒体未修改，激活记录保留精确 index 备份与 CAS 回退条件。

随后 6,394 张共同结果已通过 envelope 接回同一原入口。与 Safari 中实际观察的 102 张候选相比，
HOST/FRAME 及配置外字节相同，仅换用批量内容索引；已实际核对 `oblige` 的完整背面、
5 条主例句、义项次数和原词源。展开操作被用户切页中断，没有将它记为本轮已通过。
HTTP 读回配置一致，原 99 张入口备份与精确回退条件仍保留；
[激活摘要](../output/study-catalog-20261015/complete-render-batch-v1/activation-summary.json)不声称全书 GUI 或新的首次耗时。

`scripts/build_study_complete_web_batch.py` 从私有冻结生成器及现有源快照继续生成。
成功结果逐卡记录，可按不相交分片续跑；失败保留原原因，死 worker 不自动重启。
全部批次、剩余审核历史覆盖及正式完整包仍须完成，不能以本接线检查代替它们。
