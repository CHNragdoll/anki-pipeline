# 共同完整产物的 Anki 宿主

本页保留最初 v1 宿主节点的实现和验收范围。后续完整包已改为保留原字段 schema，
当前浏览编辑器的纯文本修复候选见 [v3 记录](../output/study-catalog-20261015/native-editor-text-v3/README.md)；
下文“追加交付字段”和“尚未生成完整包”属于 v1 当时状态。

`study_compiled_native.project_native_note` 只投影已经认证的共同 HTML/profile，
不运行第二套语义生成器，不写数据库或真实集合，也不自行分配内容版本。
网页与 Anki 的完整产物字节相同；宿主传输和启动方式适应各自环境。

原字段顺序、笔记和卡片身份保留，导出副本仅在末尾追加交付字段。
调用方必须提供已经登记、晚于封存原版的模型与内容版本。
HTML、profile、原模块、原始 side/index 和 wrapper/payload/expanded 六方来源绑定不匹配时拒绝。
本地资源使用带摘要的惰性 JavaScript carrier，不要求手机支持 file fetch。
没有扩展例句的内容仍遵循原卡行为；审核历史及其 AS/AF 载体保持原字节和权限归属。

compiled 模式先建立 profile，再启动原 Slim，跳过已经在共同生成端执行的四项语义处理。
bootstrap 按内容版本隔离；同一文档升级会清理自己持有的旧状态。
compiled→普通卡→compiled 切换不会覆盖后来安装的原加载器，也不会删除共享正文注册表。
未知模块、多个模板或尚未核验的原生 `[sound:]` 路径明确拒绝。

17 项 portable 合同通过；独立增量复核 3 项通过，无剩余 P1/P2。
[原始检查与复核记录](../output/study-catalog-20261015/compiled-native-host-v1/README.md)区分了实现版本和证据范围。
历史 train 回放中 43 条主例句、四处 AF 正文 SHA 一致，使用的是生命周期修正前的 59d7 bootstrap。

尚未接正式导出器、登记正式交付版本或生成新完整 APKG。
真实 Anki 导入、学习记录对账及手机“浏览→搜词→预览”和正常刷卡仍须单独验收。
本节点的 ready 仅表示 Slim 数据水合，不代表绘制完成或 4.464 秒速度。
