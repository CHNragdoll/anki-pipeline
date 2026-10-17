# 刘晓艳完整包的共同导出验证

新包由正式 PG revision 14 的共同 `project_book/project_note` 导出，1,960 notes/cards，6,530 媒体。
APKG 为 85,656,300 字节，SHA-256 `9bbe209fcbb6d0b4b098703125c698397f6d4a0404b7d8c6227126952a8c2eb9`。
本书无待预执行的四项语义处理，因此同一构建路径保留 authored 内容。

- `EXPORT.json`：真实完整包生成结果，未更改字段或新增笔记。
- `MEMBER-PARITY.json`：原版与新包全部 6,534 个 ZIP 成员原始字节相等；成员顺序有差异，压缩包 SHA 因此不同。
- `NATIVE-ACCEPTANCE.json`：实际 Anki 引擎在临时集合进行两次更新导入，身份/调度/标记/revlog 保留，19,600 个字段值及全部媒体字节相等，媒体缺失为 0；12 张样例取得原生模板问答字符串。

没有修改真实用户集合，没有执行手机或 GUI 验收，也没有更新远端发行。
大包保存在本机私有 `AnkiStudyCatalog/service-runtime/complete-anki-liuxiaoyan-0js2zpnx`，不复制到 Git。
归档记录省略机器绝对路径，分别保留私有原报告摘要。
