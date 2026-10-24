# 完整 APKG 的现代容器无损对照

**仅为私有 v4 中间产物，不可交付。** 这次只把旧 ZIP/deflate 传输转换为 Anki 现代格式的逐媒体 zstd frame；不解析或改写 SQLite，不改变 JS、字段、音频、例句、chunk 或审核内容。v4 仍缺后续浏览列表模板修正，也尚未通过完整桌面预览和瘦身目标。

| 实际完整 2026 包 | 结果 |
| --- | --- |
| 原 v4 | 893,171,145 字节，SHA `2f1ffb556387c6557bcff5024fe1652cb3366d1fe3373919e5202262eeeeeb78` |
| 现代容器 | 690,755,062 字节，SHA `4d6a00b9935110afa75fa4d2c4606f90e784c3c3e5a45cdc3997b4a126c081c7` |
| 实际减少 | 202,416,083 字节，22.66% |
| 编码／完整独立核验 | 123.328／26.819 秒 |
| 进程峰值 RSS | 389,906,432 字节 |

独立 reader 未导入 encoder helper。逐一解码并按块**逐字节比较**全部 89,445 份媒体及 878,039,040 字节 SQLite，不只比较 ZIP CRC、索引或内部 manifest；alias、大小与 SHA1 同时相同。源与候选全文件 SHA／身份在操作前后相同。不存在额外原始 ZIP 成员；完整结果见 [FULL_REPORT.json](FULL_REPORT.json)。

编码使用官方 `zstandard==0.23.0` CPython 3.13/arm64 wheel，libzstd 1.5.6、level 9、window log 27、单线程。SQLite 与三份最大 carrier 还由原有 pinned zstd CLI 1.5.7 独立解码，与原字节全等。[样本及实际参数](ACTUAL_SAMPLES.json)、[wheel pin](WHEEL.json)。12 项合同覆盖源变化、独占输出、成员失败、外来路径替换和硬资源限额；不是原生客户端验收。

单次完整操作仅新建私有输出，硬输出上限 1.3 GB、单成员压缩临时文件 128 MiB，保留至少 2 GiB 可用空间；结束时约 5.72 GB 可用。没有启动 GUI、原生全量导入或连接 PostgreSQL。原包、正式个人 Anki 集合与已发行附件未改。工具进程均已退出。

当前脚本仍是**诊断原型**，依赖本机安装的 Anki generated protobuf，仅用于 `PackageMetadata` 与 `MediaEntries`；[实际依赖范围](PROTOBUF_SCOPE.json)没有隐藏 backend／Collection 调用。产品接线前需要正常包依赖和共同读写边界，不能把此脚本作为各书另起一套生成器。[冻结与来源](evidence.json)。

**690.8 MB 仍大于已发行 2026 包的 399.0 MB。** 因此本结果证明容器层可无损减少约 202 MB，不代表最终瘦身完成，不把样本压缩比例外推到全部卡片，也不代表 2027 或手机已经验收。
