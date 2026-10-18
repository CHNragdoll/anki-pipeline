# 完整隔离库的索引统计对照

Browse 模板修正后，用户仍报告 Anki 卡死。真实进程采样显示字段检查正在读取大量 SQLite overflow page，界面部分等待 collection 锁。后续核对发现，测试库虽有 checksum 索引，但 `notes` 没有统计行，Anki 的实际查询选择了 `idx_notes_mid`。

该库包含 6,682 张笔记，其中 6,681 张同属词汇模型，checksum 全部不同。实际查询是：

```sql
select id, field_at_index(flds, 0)
from notes where csum=? and mid=?;
```

查询会先读取结果，再排除笔记本人。SQLite 选择 `mid` 时，对同模型各行检查位于巨大字段之后的 checksum，可能产生大量 overflow-page 读取。原查询计划和现场说明的是一次实际慢查询，尚不能据此认定所有界面卡死均由它导致。

## 完整副本实测

对关闭的自有完整 QA 库建立独立 inode 的 APFS 副本，复制前后源 SHA 与字节核验相同。实际 Anki 使用 SQLite **3.49.2**，不是系统 Python 的另一版本。唯一显式写入为 `ANALYZE notes`，未增删索引。

| 指标 | 原状态 | 统计更新后 |
| --- | --- | --- |
| 查询计划 | `idx_notes_mid` | `ix_notes_csum` |
| a，单次同一 SQL | 3.437450 秒 | 0.044867 秒 |
| a，Anki fieldsCheck | 未测 | 0.052789 秒 |
| abide，Anki fieldsCheck | 未测 | 0.001895 秒 |

统计更新耗时 0.080309 秒，生成 checksum `6682 1`、mid `6682 3341` 等统计行。结果是单次顺序对照，缓存和测试顺序有影响；不能将约 76.6 倍直接声称为整个 Browse 或翻面的加速比。

[逐格复核](PROTECTED_RECONCILIATION.json)比较了原关闭 QA 与该副本 `notes`、`cards`、`revlog` 的全部有类型 SQL 单元格：6,682 条笔记、6,682 张卡和 1 条测试复习记录全相同。源 QA 原文件 SHA 未变。此基线是此前手动卡死后的 QA，不能误称为已经回退了 `a` 在编辑器中发生的 HTML 规范化。

[测量与全部文件摘要](evidence.json)、[原查询结果](baseline-result.json)、[统计更新后结果](analyze-timing-result.json)、[诊断脚本](native-index-timing-only.py)只用于这一私有诊断，不是额外的生成逻辑。

## 尚未证明

尚未在有统计的副本上验收真实完整 Browse／Preview，不将这些后台数字当成可见界面结果。Anki 导入到目标集合后的统计状态也不能靠在源 APKG 内写统计就假定得到保证；须核对正常导入／维护流程。真实用户集合、PostgreSQL、已发行 APKG 均未修改。
