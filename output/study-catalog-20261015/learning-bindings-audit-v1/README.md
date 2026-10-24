# 现用网页学习身份的只读核对

`audit.py` 使用旧书架的三份完整目录和正式 PG 的只读一致事务，封存
`../learning-identities-readonly-20261017.json.gz`：929,649B，SHA
`986735ddee5a64b16c3cab5fbaf938b3a151a15473fab0581267e11305d99592`。
解压后的 JSON SHA 为 `0a8dbb89b877f3bec6456d0796d917fea4a3ce71e99ace23e6b8af4e9f17b81d`。

15,170 个旧 `(book,card_id,deck_id)` 都有明确目标书、来源、note/GUID/model/native card/template/unit；
保留 `liu` 等旧命名空间，不按英文拼写猜身份。正式库当时 revision 11。
2026 说明卡由旧 builder 的原身份公式及实际 native tuple 绑定；2027 说明卡由旧 Unit31 修正版
APKG 的原 note/GUID/native tuple 和全部原字段在旧页面中逐字出现共同绑定。
两个旧 guide ID 与新导出使用的 GUID 不同，报告显式保存关系，不把它们当缺失记录。

另有四张总库补充卡未进入旧学习目录：两书各 `teem`、`deep-rooted`；具体位置在结果中完整列出。
这不是丢失或自动新建学习状态的依据。正式迁移前仍要复核目录 SHA、目标 tuple 和实际学习快照；
当前报告一直 `ready_to_switch=false`，没有读学习记录、写 PG 或切服务。

本目录的 `result.json` 只含摘要；完整绑定在上述 gzip 中。`audit.py` 是当时的只读采集脚本，
再次运行不会覆盖已存在的报告。源文件后来变化时应生成新报告，不能沿用旧 pin。
