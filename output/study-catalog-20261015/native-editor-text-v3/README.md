# 浏览编辑器校验失败：纯文本传输修复候选

本节点修复 v2 的实际客户端故障，不是完整包交付或浏览验收通过记录。
用户在隔离 Anki 的“浏览 → 预览”看见“完整卡片无法校验”。实际编辑器会删除字段中的
`script`／`link`；v2 把交付描述放在 Meta 的 script 末尾，编辑器保存后描述消失。
原稿 Meta 仍在，正常刷卡和浏览预览因此产生不同结果。
[v2 实际失败、源包与客户端修改范围](../complete-anki-redbooks-v2/README.md)继续保留。

v3 继续使用同一原生 projector／binder，把描述改成唯一、终端的纯 ASCII 文本 token：
`[[study-native-delivery:v3:<base64url>]]`。原十字段结构和顺序不变，移除 token 可恢复原 Meta；
其余字段和所有已认证的共同 HTML、profile、原句、chunk、审核、音频不重新生成。
Python 与 JS 使用一致的 UTF-16 键排序和安全整数规则；JSON／UTF-8／base64url 非规范编码、
重复标记及非文本内容拒绝。全局语义资源 JSON 序列化器未改，不因此重写共同资源。

两年全部 13,212 个原 Meta 已检查，均不含会被编辑器规范化的 `<`、`>`、`&`、换行、NBSP
或控制字符。该清单只证明本次真实输入；不能宣称任意未来带 HTML 的 Meta 都适用。

两卡 `abide`／`venture` 已通过实际安装 Anki 的默认更新导入到独立 QA 集合，
身份、卡片调度、旗标和 revlog 保留。这个仅 192,736 字节的测试包依赖 QA 已有完整媒体，
**不是独立可用下载包，也不是手机完整包**。实际浏览编辑器保存和预览的观察仍待完成。
工具打开 Browse 时两次触发 NSAccessibility 层崩溃，需用户手动打开该窗口，再继续检查。
实际用户集合没有导入本候选；更早工具误启动普通 Anki 的事件保留在 v1 记录中，不能用本次隔离范围否认它。

`fixture.json` 固定测试包、当前 host 与两卡 Meta 摘要；`native-and-export-tests.log`
只证明可移植运行时和导出合同，不替代真实 Browse、手机或最大卡速度。
独立归档校验器已增加显式 `meta-text-v3`，旧 v1/v2 路径保留，38 项检查通过并独立复核。
该结果证明校验器的合同；尚未生成、检查真实两年 v3 完整归档，详见 `archive-verifier-checks.json`。
修复尚未登记到正式 PG native 版本，未重建两本完整包，未推送、PR 或更新 Release。
当前 v2 完整候选仍为 900.8／821.7 MB，包体积目标未通过。
