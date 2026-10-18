# v5 本地阶段记录（2026-10-18T10:07:24.568536+00:00）

本目录仅封存小凭据，绑定源码提交 `77caf5cff61f64975856bc2b954f12a8639668fd` 和 operation seal `82b106cbce619c5d8c377601e766e8c2cc017cd67d5395e0a6235cb43ef5a519`。未修改 README、源码、HEAD 或发行；未重新导入 Anki、连接 PostgreSQL、打开 GUI、读取正在增长的 native QA 输出，未复制 SQL/APKG/媒体/完整 carrier cache 或大型 ledger。

| 年份 | modern 候选 | 已发行旧包 | 当前结论 |
|---|---:|---:|---|
| 2026 | 503,725,729 B（503.7 MB） | 399,025,978 B（399.0 MB） | 仍大于旧包 |
| 2027 | 482,770,183 B（482.8 MB） | 354,073,910 B（354.1 MB） | 仍大于旧包 |

两本 modern 容器均已有完整独立逐字节对账：SQLite 原字节、每个媒体别名的原字节/大小/哈希及额外成员全部相等，绑定各自封印的 v5 payload；这不表示 modern 与旧发行包整包字节相等。见 [2026 完整报告](modern/2026/FULL_REPORT.json)、[2027 完整报告](modern/2027/FULL_REPORT.json)。**无损转换对账已通过，瘦身目标尚未达到。**

2026 已完成安装版 Anki 原生导入及两次默认更新：6,682 张卡、身份、测试学习记录和全部 67,699 个媒体通过核对，66,813 个字段值全部原样或仅由 Anki 作 NFC 规范化；见 [实际导入](native-2026/NATIVE_DEFAULT_IMPORT.json) 和 [来源及保留副本](native-2026/NATIVE_DEFAULT_IMPORT-retained.json)。2027 的这一轮原生导入尚未执行。

2026 第一轮真实官方窗口未通过验收：[原始观察摘要](native-2026/FIRST-GUI-OBSERVATION.json)。Browse/Editor 出现长停顿，最长事件循环间隔 20.171 秒。后续从封印原字段、原 AS 资源和原作者代码独立推导确认：425 组同段同义内容隐藏 534 个重复展示，3,513 条记录仍保留；一条原审核投影另补出原译分块对照。[完整预期](native-2026/EXPECTED-A-AUTHORED.json)及[来源收据](native-2026/EXPECTED-A-SOURCE-RECEIPT.json)与历史 ready 的全部文章哈希和隐藏状态相等。没有用观测值反填预期。

另一个封存的隔离副本中，安装版的同一重复检查 SQL 选择 `idx_notes_mid`，单次 9.038 秒；仅 `ANALYZE notes` 后选择 `ix_notes_csum`，单次 0.148 秒。12 张非统计表的结构和全部 typed rows 均相同，原库不变，见 [统计对照](native-2026/QUERY-STATISTICS-CONTROL.json)。这是 Python SQLite＋同义 field0 函数的查询诊断，不是 GUI 耗时，也不是已应用到真实集合的修复；APKG 导入不会将这些客户端统计搬到接收集合。

该仅更新统计的副本随后以官方 Anki/Cocoa 在另一独立资料库实测：[完整观察摘要](native-2026/GUI-STATISTICS-CONTROL.json)。`a` 首次和重复背面的全部 3,513 项文章哈希匹配，`abide` 两处句子、2012 筛选及 `venture` 的五条保留记录均匹配源预期。三词翻背面依次为 6.014／0.766／0.775 秒；`a` 重复翻回正面 1.108 秒、重复背面 5.170 秒。计时包含语义哈希验证和轮询，不能当纯首绘速度。最长事件循环停顿仍有 11.034 秒，关闭监控仍记录 PermissionError；最终所有自有进程均已退出，来源库和媒体未变。

**这轮只通过了三词完整显示与指定交互，不代表速度、整个客户端或手机通过。** 实际学习库未修改；2027 本轮原生导入仍待完成，候选未交付。继续分别记录内容、查询、界面、速度和关闭结果，不能合成一个“全部通过”。

已有真实登记保护凭据：仅 3 个登记键、10 个学习表共 15,177 行及其它受保护状态前后完全一致，见 [登记保护](registration/REGISTRATION_PROTECTED.json)。[PostgreSQL 25 项回归](postgresql/POSTGRESQL.json) 是隔离 schema 测试，与真实登记和客户端验收分别记账。

三轮明确授权回收的最终凭据在 [cleanup](cleanup/)：退休派生 APKG 与两个 INTERIM 硬链接按精确范围回收；旧 QA/派生 SQLite 缓存先完整无损 gzip 归档、独立解压逐字节核验，才移除裸副本。不存在的缓存仅记录未操作。gzip 仍保留全部旧字节；未泛化为原始数据删除，也不宣称已退休容器可由 v4 逐字恢复。原始包、当前 v4/v5 输入、真实 profile、GUI clone、备份及媒体均受保护。

[MANIFEST.json](MANIFEST.json) 记录每个来源的完整路径、原始 SHA/大小/稳定身份，以及脱敏副本或摘要的独立 SHA。所有数据库连接串及凭证键均经过收集脚本的删除/脱敏检查。HEAD 保持不变；文件仅位于 ignored output，等待父任务选择保存 Git 节点。
