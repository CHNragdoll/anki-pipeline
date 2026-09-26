# v3.0.0-rc.1 发布决定与证据入口

## 本次授权的等效控制

2026-09-26，用户在解释后回复“ok”，批准仅本次 `v3.0.0-rc.1` 使用以下方案：仓库保持私有且仅 owner 访问；通过真实 PR #1；最新提交的 Python 3.11/3.13 CI 必须通过；独立审查完成后才合并、创建 annotated tag 和私人 prerelease。授权随本次发布完成而用尽，最迟 2026-10-03 到期，不适用于后续版本。

GitHub 私人分支保护 API 返回 403，未开启服务端强制保护。这是 VCS-002 明文允许且 owner 明确批准的 equivalent，不是把 GitHub 分支保护声明为已开启。风险是 GitHub 不能阻止 owner 绕过流程直接推送；本次由执行者核对 PR head、CI、审查及合并记录。后续版本须重新检查 GitHub 计划/保护设置或获得新的处置决定。VCS-006 的集成记录通过显式 merge commit 保留，不能直接推 main 代替 PR。

## 发布范围与验收链

本次只交付私人源码候选版及文档证据，不分发学习词库、媒体、数据库、APKG 或依赖二进制。Anki 客户端导入、旧复习进度迁移、生产运维及退役不属于本次源代码候选验收；这些限制继续保留，不宣称对应客户端通过。

| 验收要求 | 实现与设计 | 验证、审查 |
| --- | --- | --- |
| 原资料只读、迁移保留与恢复 | migration/store、ARCHITECTURE.md | local-trial-verification.json、test_integration.py、REVIEW.md |
| 精确词形、译文 ID 对齐与过期表防护 | text/forms/translations | tests/、61 项单元集成测试、REVIEW.md |
| 稳定牌组、媒体校验、可恢复输出 | packaging/pipeline/cli | 卡包 CRC/媒体摘要、test_media.py/test_safety.py、真实试运行 |
| 词表/PDF/可选联网与本地 CLI | inputs/pdf/cli、OPERATIONS.md | 固定网页模拟、真实 PDF smoke、doctor/migrate/check/build/restore |
| 页面、音频与错误反馈 | templates、preview | VERIFICATION.md 的浏览器截图/播放观察、CLI 异常与恢复测试 |
| 可重现源码、风险与版本 | uv.lock、project-profile、CHANGELOG | PR #1 标签、双版本 CI、独立审查、发布清单 |

原始计划见 PLAN.md；实现审查与修复见 REVIEW.md。既有 conformance.json/CONFORMANCE.md 是发布前的历史检查点。新的批准取代其中“没有等效方案授权”的旧结论；它们不是本次发布后的最终状态。最终 `release-manifest.json` 与 `release-conformance.json` 随 GitHub Release 提供，记录真实 merge SHA、tag、源码归档 SHA-256、验证证据和各阶段判定，避免在 Git 提交内虚构它自己的未来 SHA。

## 依赖替换与退出

依赖版本由 pyproject.toml/uv.lock 管理。网络 enrich 为显式可选步骤，关闭后仍可离线迁移/制卡；provider 变更只涉及 inputs.py 及固定页面测试。PDF 引擎封装在 pdf.py，可停用 extract，继续使用已保存的句子/CSV；替换引擎需重验来源与切句。genanki 封装在 packaging.py，替换须保留 GUID/模型字段并重验卡包。SQLite 可通过受控 CSV 导出、在线备份与新路径恢复退出；不直接原位切换存储。每次依赖升级都更新 lock、审查许可/漏洞并跑受影响检查。

## 发布与回滚

顺序：提交本决定 → 最新 CI/审查 → PR merge commit → 验证 main → annotated tag → 构建并核对源码归档/证据 → 私人 prerelease。任何失败停止后续动作；不重写已发表 tag。回滚可继续使用完全保留的旧 V2.0；新版数据库从备份恢复到新路径并对账。本次不写用户 Anki 集合。
