# 翻面失败后的永久等待：两处终止处理修复

当前正式网页仍为 v19。本轮从原 FRAME `d7e60fccd7fc6158f8c29f5128a993e14e07e591c91b3a948b70662a27a1b59a`
取得真实控制函数，先在隔离回归中重现两个缺陷，再修改共同源码。尚未部署，不宣称已确认或解决 Safari 现场卡死。

## 已重现的控制流

1. `show` 禁用按钮后，末次 `promote` 因几何、字体或 child 状态失效而返回 false。
   原调用只处理 rejection，结果没有报错、重试或恢复按钮；真实 disabled 按钮也不再响应点击。
2. `waitPrepared` 的异步 rAF 回调捕获错误后直接向外 throw，无法拒绝早先构造的 Promise。
   原等待保持 pending，后续 rAF 也不再排队，十秒检查没有机会继续执行，翻面按钮一直禁用。

这是可达到的源码缺陷；夹具控制末次状态和异常，并未证明用户此次 Safari 恰好走了这两个分支。

## 最小修改与边界

- 异步检查 catch 调用已有 `reject(error)` 包装，释放一次 observer/cache，以原 Error 拒绝等待。
  初始同步调度异常仍按原方式处理。
- 末次 `promote` 返回 false 且 `ownsView` 仍确认当前 owner 时，抛明确错误。
  继续由原 click catch → scoped fail → HOST 失败处理接手；不显示未就绪内容。
- 旧请求、取消和 A→B→A 不能解锁新请求，不能用无条件 finally 改全局 busy 状态。
- 没有新增等待窗口或重试，没有省略来源、native、child、字体或三次稳定几何检查。
  PostgreSQL、APKG、原文、计数、媒体和学习记录均不改。

## 检查与证据

旧源码运行新回归先 RED：`Missing expected rejection`。修复后8个子场景通过：
稳定成功、末次几何/字体/child失效、真实异步rAF异常、取消、ABA和foreign owner。
异常验证同一Error、无global error、无后续rAF、observer仅disconnect一次。

直接受影响的旧gate合同同步改为明确拒绝；static history整页摘要先逆回两处修复核对旧pin，再固定新pin，
保留双向检查。terminal、gate、static history与已有shell/front合并单次6项通过，23.646秒，无skip。
一次围绕实际diff的独立复核已关闭旧合同P2，无剩余P1/P2；没有重复运行未改变的数据审计。

新 FRAME 为 `7882619ef47acab970cc5eba280788c9840c18ad325674697a82fd0f9e0c9773`，
FRAME HTML 为 `661bf17e4c9e57f2bca775617feb2195b6e2e6f2a0738c3b866ddce47edc9549`。
两处精确逆变换恢复原v19 FRAME；HOST不变。原始证据保存在
`output/study-catalog-20261015/terminal-failure-reviewed-v1/`。

下一步仅在独立QA页实际核对正常完整翻面与原内容，再决定三入口条件推广。
这个可靠性修复不等于首次长卡已经秒开；Safari与性能总目标继续单独验收。
