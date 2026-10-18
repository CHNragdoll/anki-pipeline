# 原生 Browser 列表模板修正候选

2026 v4 完整候选在实际手动测试中仍失败：用户找不到指定的 `abide`，其他卡 Preview 崩溃，进入 Browse 也卡顿。此次手动崩溃的主线程仍在 libqcocoa／NSAccessibility；不能再归结为“只有工具操作才会崩溃”。崩溃摘要、包状态和核对结果见 [evidence.json](evidence.json)。

## 已确认的列表错误

Anki 26.09.3 的实际后端使用源 `abide` 模型和全部十字段，在独立的一张卡小库复现：

| Browser 模板 | 实际 Question | 实际 Answer |
| --- | --- | --- |
| 空，回退普通模板 | 9,737 B 的 Meta／内部数据，未显示 abide | 同样 9,737 B |
| Word／Definition | abide，5 B | 21,244 B，仍过大 |
| Word／SimpleDefinition | abide，5 B | 空，原字段本就为空 |

普通模板的隐藏 `<template>` 会被列表后端转成文字，JavaScript 不会在该列表里执行。Browser 列表与真实完整 Preview 是不同调用路径；专用 Browser 模板不替换刷卡或完整预览。

共同原生适配器只在 `bqfmt`／`bafmt` 缺省或精确空串时填入静态原排序字段；此词卡对应 `{{text:Word}}` 与 `条目：{{text:Word}}`。短前缀避免 Anki 将 Answer 与 Question 相同的开头剥去后变为空。已有非空作者 Browser 格式保持原样；没有按书或按单词分叉。字段必须是原模型的合法、唯一、非 Meta 排序字段，不能将内部数据作为替代显示。

正常 `bind_native_delivery` 的独立一张卡小库已在实际后端输出 `abide`／`条目：abide`，完整预览 HTML 和 body、普通模板及十字段逐字不变，见 [后端报告](native-backend-fixed.json)与[运行脚本](native-backend-operation.py)。Python 3.13 的 native 39 项、独立归档 verifier 47 项全部通过，修复前 RED 日志保留；独立差异复核无 P1/P2，并另跑新增 6 项通过。Python 3.11 未运行。所有这些结果均不代表 GUI 已验收。

## 完整测试库候选

实际完整 2026 QA 库有 **6,682 张笔记／6,682 张卡**。操作前使用完整数据库文件备份，逐成员核过 SHA；只修改该隔离库的 Browser 格式。之前试验的编辑区 `collapsed`／`plainText` 设置已全部恢复原值，不能将本次结果归功于隐藏编辑字段。

`abide` 与 `venture` 的实际后端列表分别返回正确词名和短 Answer。两张卡正常 Preview 的 Question／Answer 完整字符串及全部字段逐字不变；全库 `notes`、`cards`、`revlog` 每行摘要前后相同，身份和测试学习状态保留。[隔离 QA 操作审计副本](owned-qa-operation.py)不属于第二个正常生成入口，也未修改 PostgreSQL、APKG 或真实用户集合。

已用显式独立目录重新启动 QA Anki，未绑定 CUA 或调用原生界面读取，实际手动 Browse／Preview 结果 **PENDING**。此轮没有新的成功界面截图，不借用旧截图宣称已通过。

## 完整包和剩余工作

原年份处理器修复已进入 v4 两份完整归档，独立归档核对均通过。2026 v4 的默认更新／重复导入通过；2027 的 v4 原生导入尚未运行。上述包仍不包含本次 Browser 格式修正，也没有客户端通过结论。

先解决并实际验收 Browse／Preview，再重建包含同一修正的完整包。手机、最大卡首翻速度与无损瘦身另验；当前不保证秒开。已发行附件、原书架入口和真实 Anki 集合没有被本次候选替换。
