# 完整 Anki 交付前的安装与临时副本核验

共享审核适配修复提交 `a01377b` 后，干净 Git 源码构建 wheel，并在仓库外安装。
178 个包文件、183 个 wheel RECORD 摘要全部一致；21 项安装后合同及四个 CLI
帮助入口通过，没有连接数据库。未跟踪的三个实验文件没有进入安装包。
此前 `152f316` 安装后出现的审核 `text` 错误保留原失败报告，当前版本已复验通过。

导出前仅处置本任务生成的旧恢复测试副本 `study_restore_20261015_full_v1`：
先重新核对保留 gzip 的完整摘要，再用一次只读事务核对全部 24 表、8,118,998 行
完整 payload；耗时 590.256 秒，与原备份逐表相等，没有独有持久数据。
正式总库是独立的 `study_catalog`，保留当前 34 表和 revision 14。

处置事务再次核对数据库、schema OID、owner 和全部关系身份，取得排他锁，采用
同事务的多表 `DROP TABLE RESTRICT` 与 `DROP SCHEMA RESTRICT`，没有使用 CASCADE。
提交前后正式总库的全部关系身份、metadata 摘要、revision 和 15,174 条 note 数一致。
原 7.13 GB gzip、当前 34 表完整备份及全部恢复证据均保留；未删用户资料。
实际可用空间由 6,663,749,632 增至 16,757,641,216 字节，不把关系计费直接当作回收承诺。

本次没有登记正式原生版本或生成完整 APKG。最终全量生成、包体大小、原生导入与
实际客户端验收仍需分别完成。证据见
[`native-delivery-readiness-v1`](../output/study-catalog-20261015/native-delivery-readiness-v1/summary.json)。
