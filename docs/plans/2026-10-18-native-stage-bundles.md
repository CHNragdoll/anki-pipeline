# 原生载体按实际加载阶段合批

工作树：`anki_rebuild`，分支 `feat/unified-study-database-20261015`。
本轮继续已有完整数据库／统一消费者任务，不创建新分支，不发布或替换发行附件。
用户未跟踪文件保持原样。

## 原因与选择

v6 的完整 modern 长度为 644,359,748 字节，大于 v5 的实际 503,725,729 字节，
不能继续生成第二本同方案完整包。当前按整张 profile 的 consumer 集合、且仅对小于
256 KiB 的载体合批；大 HTML 和 profile 无法共享同一压缩帧。
直接扩大这个阈值可能把背面正文随 packet 带进正面，所以要先细化阶段。

完整 profile 文本省略统计尚未完成：修正完整 Meta 读取后，实际确认 6,681 个
compiled profile 和一张指南卡。最初仅测 13 项便触发 512 MiB 内存守卫，
该次最终源包重哈希未完成。流式分配和分块修正后的最新尝试完成 96 项，
在第 97 项的载体解析阶段触发同一内存守卫；最终源包完整 SHA／身份与
SQLite 绑定均通过。这仍不代表整包，暂不采用新的 profile 存储 schema。

## 本轮源码范围

1. `study_compiled_native.py` 在现有来源、HTML、profile、资源认证之后，输出仅供
   合批规划使用的物理载体阶段事实。HTML、profile、binder 为 `back-initial`；
   packet、policy、提取后的 loader 为 `front-initial` 和 `back-initial`。
   其他外部脚本、CSS 和 AS/AF 历史媒体暂不推断阶段，标为未知并保持独立载体。
   同一物理载体的全部调用必须合并；任何未知调用都阻止其参与合批。
   `classify_native_media_stages()` 是共同纯函数，仅消费上游已认证的 descriptor、
   packet 和 policy；正常投影和复用封存产物的构建均使用它。
2. `study_catalog_export.py` 在所有原始 note 投影、物理去重之前汇总
   `(card id, logical profile SHA, stage)` consumer。任何 note 中的未知使用
   都排除该载体，即使其他 note 已提供已知阶段。不得依赖 note 处理顺序。
   `record_media_consumers()` 是共同汇总入口，缓存构建不复制此规则。
3. `study_native_carrier.py` 仅合并具有完全相同非空 consumer 集合的载体，
   允许大于 256 KiB 的成员，但多成员合计仍至多 8 MiB／256 个。
   无 consumer、单个超过 8 MiB、其他媒体均原样直通。继续流式认证和封包，
   不增加整批临时载体副本。
4. 独立归档校验器保留自己的语法和常量，把组内成员上限同步为至多 8 MiB；
   组总大小和成员数、规范串联语法、物理／逻辑 SHA 等检查全部保留。

一套规则应用于所有书籍。wire descriptor、逻辑资源 SHA、完整 HTML/profile、
原十字段、历史树、原媒体、计数、作者执行顺序和旧 binder 不变；不改 bootstrap。
固定的 packet 仍含既有 back_children，本轮不声称拆除了它内部的跨面内容。

## 验证与交付条件

- 先有失败复现：大背面 HTML/profile 未合批；正面 packet 不得进入其合批。
- 覆盖超过 8 MiB 的成员、8 MiB／256 上限、跨 note 去重、任何未知使用、
  相同原字节多名称、处理顺序稳定性和已有暂存篡改检测。
- 小型真实 projection/export 测试证明原字段、逻辑资源和 wire descriptor 不变，
  仅物理 transport 地址改变。测试不接触正式 PostgreSQL 或个人 Anki。
- 围绕实际最终 diff 做一次独立审查，修复明确问题后本地 Git 留节点。
- 源码合同通过后仍须完整压缩统计、两本真实构建、逐字段／逐媒体对账、
  原生导入、Browse／Preview 与刷卡验收；未执行的范围继续写明未完成。
  包体和客户端结果未通过前不替换现有下载。

## 空间与回退

仅执行小型源码检查，使用新建的项目测试临时目录；可用空间低于 128 MiB 或
测试临时输出超过 64 MiB 时停止。当前空间不足以做全量构建，不通过删除其他文件
或降低完整构建空间门槛绕过。正式数据和发行附件不变；源码改动可单独撤回，
不需回滚正式数据库。本轮六份经明确授权清理的旧缓存及其恢复 APKG 另有回执。
