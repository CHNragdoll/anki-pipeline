# 共同完整卡片产物接入 Anki 导出

`export_book`、`export_batch` 和内部 APKG 输出接受显式 `compiled_delivery` 与
`native_versions`。两宿主消费同一共同生成器的完整 HTML/profile；导出器不再执行语义生成。
未传入新参数时仍走原导出路径。

每个 note 输入包含共同结果、原 prepared/policy，以及在同一只读投影快照取得的
`compiled_source_sha256(note)`。这个摘要绑定原字段、模型和身份，仅排除独立登记的模型版本。
版本映射使用整数原生 ID，必须与已登记投影相等，并高于封存版本；不自行生成时间戳。
同一模型混合 compiled/authored 输入会明确拒绝，不能为绕过检查更换模型身份。

原 10 字段、GUID、note/card/model/deck 身份、调度、复习记录、删除记录及原媒体保留。
仅追加原生交付字段及共同载体。载体在私有暂存区按摘要去重，封包时再校验实际流字节；
载体、来源或版本不一致时不发布最终包。兼容 binder 升级由调用方显式执行，原构建记录保留。

23 项小型合同通过，其中新增 8 项经独立复核通过；覆盖真实 SQLite/APKG 成员、
默认成员字节不变、错源/错版本拒绝、多 note 去重与暂存篡改拒绝。
只读 catalog 在此组测试中使用 fixture；不等于真实 PG 版本登记、三本全量构建或原生客户端导入验收。

独立审查记录：
`/private/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-native-export-review-20261017-q40vos4z/REVIEW.json`，
SHA-256 `5fceb4cf63aa3c0abf87d23b1b18654fc2059c675f55bcfd807b94eabdccd45c`。
