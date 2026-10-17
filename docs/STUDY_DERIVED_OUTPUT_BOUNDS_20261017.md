# 完整卡片的派生产物上限修复

真实 `according` 的共同语义产物为 75,240,568 字节，超过旧的 64 MiB 派生 HTML 输入上限。
正文和原失败作业均保留。派生 HTML 上限改为 128 MiB，共同输出存储及读者改为与
profile emitter 原有上限一致的 256 MiB。原始输入仍为 64 MiB；历史 AS/AF 文件仍为
64 MiB，历史源 artifact 仍为 128 MiB。

沿用已完成的语义产物重新生成 profile：138,369,350 字节；fields 为 138,367,553 字节。
共同读取器已实际读取并核对两者的字节数与 SHA，正文锚点逆变换完全一致。
没有重跑原语义生成，没有修改原文、计数、媒体、数据库或学习记录。

输入及共同构建共 29 项检查通过。独立复核的两项边界检查通过，两处阻断均关闭。
这些是生成与读取验证，不代表 Safari 速度或全书客户端验收。

本机原始验证记录：
`/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-according-profile-resume-20261017-pq26osy7/BOUNDS-VERIFIED.json`。
独立复核记录：
`/private/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-derived-limit-final-review-20261017-uldlrjty/REVIEW.json`，
SHA-256 `6e76a117163fbcef80a7eb8b26eb37bd235a47202943a4d95099a987d098ce5d`。
