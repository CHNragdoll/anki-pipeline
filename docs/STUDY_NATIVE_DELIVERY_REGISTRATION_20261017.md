# 原生交付的显式版本登记

`plan_native_delivery(target, books)` 在只读 RR 快照核对指定模型的完整 note 覆盖、
原字段/模板/身份指纹，以及共同构建记录和 binder 摘要。调用方先核验这些共同产物原件。

`register_native_delivery(target, plan, journal=新私有目录)` 在显式 READ COMMITTED 事务中
取得共同写锁，再核事件 revision、全部来源和三个 metadata 原值。仅更新既有模型版本、
内容版本和一个交付登记键；复用已有单调递增算法，并重新投影有效版本供导出器使用。
同一指纹重放幂等，旧来源或旧 metadata 计划拒绝。

journal 只备份此次三键写集，不替代操作前的完整总库备份。目录、原始文件 inode/字节摘要
及封存文件经持有 fd 与 fsync 核验；替换目录、篡改备份或替换为 FIFO 均拒绝。
最终提交确认文件失败时明确报告“已提交”，不能据缺少本机标记重写数据库。
未发布回退还要求调用方固定 journal 摘要、`unpublished=True` 和当前 after/source 全部一致；
不能覆盖后来的版本或资料修订。

17 项随机隔离 PostgreSQL 合同通过；最终唯一 O_NONBLOCK 补口后的五项相关目标通过，
独立复核五项通过、无剩余 P1/P2。没有在正式总库登记版本，没有生成新的红宝书完整包，
也没有改用户集合、学习记录、字段、媒体或事件/对象表。

本机冻结证据：
`/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-native-delivery-registration-final-20261017-8zdgdqm0/REPORT.json`，
SHA-256 `3cbdd1f6eaab528b618aa2d223ef141a6ee424313e443d01fbc68927546d40c4`。
