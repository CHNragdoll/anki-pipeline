# Anki 载体接入共享审核正文

完整背面方案不变。干净 wheel 的仓库外测试发现：共同 profile 已用
`textKey`／`initialHistoryText` 共享审核全文，原生适配器仍读取旧 `text`，导致
`KeyError('text')`；初始闭合审核的 AF 资源也没有单独加入原生载体。

原生适配器现在读取共同 profile 的这两类依赖，保留旧 inline 格式兼容。每份审核
仍同时核对原 AF 字节摘要、原惰性注册、完整文本与逻辑摘要；共享键和 inline 文本
互斥，缺表、错误全文、错误资源及未消费银行条目均拒绝。初始 slot 不接受额外
`textKey`。没有复制判义逻辑，也没有改变共同语义产物、原字段、正文、chunk 或计数。

实际原生 bootstrap 与原加载器的隔离执行覆盖：

- 只有初始 AF 的卡片：闭合时保留原占位，展开后显示完整 Unicode 原文。
- 同时有初始 AF 和两条后续 AS／AF 的卡片：三处均可展开，原编译绑定不失效。
- 旧 inline 格式及两种模块来源继续兼容；原 Anki 外壳、控件与生命周期保留。
- 缺资源、重封原始摘要但更换逻辑正文、共享键冲突和错误银行均拒绝。

完整适配器测试及独立复核证据见
[`native-shared-history-v1`](../output/study-catalog-20261015/native-shared-history-v1/summary.json)。
该记录不代替两本完整包、真实客户端导入或手机验收；未写入正式 PG 版本，未修改
用户 Anki 档案，未发布远端附件。
