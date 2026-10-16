# Fine 编译状态恢复实验

这些文件仅保留隔离实验与反例，**没有接入 Anki／网页生成器或正式入口，也没有证明提速**。
它们不属于安装包运行时，不应用 `candidate-fine.js` 替换正式脚本。

在项目根目录使用已有开发依赖运行：

```sh
node --test tests/fixtures/experimental-fine-plan-v2/protocol.test.cjs
```

原 Fine install 在编译时执行相同语义，并记录真实 Map、属性操作和 active reset。
重放使用调用方持有的外部 SHA、模块／来源／metadata 版本与完整 Fine 语义输入图，进入原闭包及 handle。
语义计算因此移到编译时，不能声称运行时还独立重算了 whole／target 判断。
Fine 不读取或替换 Text；全文来源证明仍属于上游。未知继承状态、非枚举消费字段或不支持的输入写入前拒绝，
普通 install 仍可用。原 refresh、observer 和条件式 dispose 保持。

14 项小合同覆盖已确认的两个继承状态反例、输入图关系、外部锚、取消、后增内容、原元素／Text 身份及恢复。
`edits.json` 可精确逆回原 Fine，`fixture-seals.json` 记录实际冻结字节。
`compiled-entry.js` 是嵌入候选的协议源；其余原始运行时及 whole-probe 副本是固定版本测试输入。

真实 Safari 的 `abolish` 另次捕获／重放、最终 DOM 与交互已核对，详见
[研究记录](../../../docs/STUDY_SAFARI_DIGEST_CANDIDATE_20261016.md#fine编译计划的隔离验证与停止条件)。
这不代表构建时 producer、正式集成、换卡异步生命周期、手机／音频或最大卡性能通过；
完整输入图与操作验证本身仍有成本，进入产品前必须单独证明净收益与其余生命周期。
