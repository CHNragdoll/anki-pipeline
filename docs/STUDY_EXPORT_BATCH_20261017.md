# 共同导出的单次 PostgreSQL 快照

`export_batch()`现已加入共同导出器。它让多本书的网页和 APKG 使用同一个只读
REPEATABLE READ 事务，保留既有 `project_book`、`project_note`、原生身份、修订版本和媒体路径。
本次没有生成三本全量新包，也没有修改正式数据库、运行服务或发行附件。

## 接口与交付边界

```python
from anki_pipeline.study_catalog_export import export_batch

requests = [
    {"book_id": book, "format": format, "name": book + suffix}
    for book in ("redbook2027", "redbook", "liuxiaoyan2027")
    for format, suffix in (("apkg", ".apkg"), ("web", "-web"))
]
report = export_batch(target, requests, new_output_directory)
```

`target`使用既有显式 PostgreSQL 配置，输出目录必须尚不存在。请求只接受
`book_id/format/name`，提前拒绝路径穿越、保留名称、Unicode／大小写同名和重复书籍格式。
连接一次、每书投影一次，所有字段读取和资源生成均留在同一快照；不在导出事务中写 PG 缓存。

根目录的 `manifest.json`记录 PostgreSQL 快照、内容修订、各书来源、组件、模板、运行时及产物报告摘要。
根 `COMPLETE.json`最后发布并绑定 manifest 的完整字节摘要；子网页自己的完成标记不表示整批已完成。
完成标记在私有文件内完整写入、同步和关闭，再以不覆盖目标的硬链接发布，发布前后核对自有 inode 和实际字节。
网页文件同样拒绝覆盖抢先存在的文件或目录。

失败保留已完成子产物、当前私有 stage 和有界 `FAILED.json`，不把半成品标为成功。
成功时仅移除空 stage；非空 `.partial`可能保留构建文件和外部添加的诊断文件，**不属于 manifest 的交付产物列表**。
因此 APKG 文件内容和大小不因这些私有构建文件改变；不要将整个隐藏构建目录当成卡包发布。
外部已占用的文件或标记不删除、不替换。

## 已执行的验证

- 最终源码 SHA：`c0f430139038f10397607e4ee5b3e240caf73adf8c4d74a747facd22f2ca3054`。
- [27 项测试](../output/study-catalog-20261015/shared-export-snapshot-v1/tests.json)全部通过，无跳过，
  其中包括既有 10 项隔离 PostgreSQL 合同、原生版本与两端共同修订回归。
- 独立审查对最终 diff 运行 17 项纯／小 SQLite 合同；
  [三组真实 RED 和关闭结果](../output/study-catalog-20261015/shared-export-snapshot-v1/review.json)保留完成标记、
  stage 文件保留和网页无覆盖发布的反例。
- [真实 PostgreSQL 并发验证](../output/study-catalog-20261015/shared-export-snapshot-v1/postgresql-result.json)：
  三本小书、六份实际产物使用同一个连接和 revision 6。第一份生成后，另一个连接提交 revision 7，
  六份产物仍全部保存旧释义；随后独立单份导出读到新释义。新建的随机隔离 schema 已清理。

复跑真实验证需显式设置测试连接；脚本只操作新随机隔离 schema，不以正式内容作为写入样本：

```sh
ANKI_STUDY_TEST_DSN='<explicit test connection>' \
  PYTHONPATH=. .venv/bin/python -B \
  output/study-catalog-20261015/shared-export-snapshot-v1/verify-postgresql-snapshot.py
```

归档内带 `initial` 的结果对应修复发布边界之前的源码，仅保留历史，不作为最终版本验收。
本接口补齐共同导出的快照一致性；compiled 双端生成、全量新包、原生客户端和最大卡速度仍按原计划继续验收。
