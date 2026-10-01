# main 分支保护与维护者同意

维护者要求保护主分支，且每次合并必须先取得本人同意。维护者选择的执行方式是 **GitHub 强制 PR / CI，Codex 在对话中逐 PR 取得明确同意**。

## GitHub 已启用的规则

2026-10-02（Asia/Shanghai），在 `CHNragdoll/anki-pipeline` 的 `main` 分支启用以下保护，并通过独立 GET 回读核对。机器记录见 [branch-protection-verification.json](branch-protection-verification.json)。

| 规则 | 实际设置 | 作用 |
|---|---|---|
| 必须经过 PR | `required_pull_request_reviews` 已配置 | 禁止直接向 `main` 推送。 |
| 必须通过两项检查 | `test (3.11)`、`test (3.13)`，绑定 GitHub Actions app `15368` | 同名外部状态不能替代该 app 的检查。 |
| 基础分支必须最新 | `strict: true` | PR 必须与最新主分支一起满足检查。 |
| 管理员也受保护 | `enforce_admins: true` | 管理员身份不免除以上规则。 |
| 禁止强制推送 | `allow_force_pushes: false` | 防止改写主分支历史。 |
| 禁止删除 | `allow_deletions: false` | 防止删除主分支。 |
| 讨论必须解决 | `required_conversation_resolution: true` | 未解决的审查讨论会阻止合并。 |

GitHub 必需的审批人数为 **0**，没有要求独立账号的 Approve。当前 PR 使用维护者的同一 GitHub 账号创建，GitHub 不允许作者审批自己的 PR；维护者明确选择在本对话确认。该设置仍要求走 PR，但 **GitHub 不会核实对话里的维护者同意**，不能把它描述成平台强制的人类审批。

## Codex 每次合并前的执行规则

根目录 [AGENTS.md](../AGENTS.md) 将同意规则保存在仓库内：

1. 完成实际改动、必要验证和检查，提供可审查的 PR。
2. 说明该 PR 的编号、最终内容、检查结果和重要限制。
3. 明确询问维护者是否同意合并 **这个 PR**，等待本人回答。
4. 获得明确同意后，再核验当前 diff 和检查；如果内容发生实质变化，重新取得同意。
5. 合并后核对远端提交、CI 和实际状态。

CI 通过、子代理审查通过、维护者是 PR 作者、此前同意其他 PR、或泛化的“发布版本”指令，都不能作为后来 PR 的合并同意。不能预先开启自动合并，也不能削弱分支规则来绕过等待。

## 记录和时间边界

- 正式版发布 PR [#5](https://github.com/CHNragdoll/anki-pipeline/pull/5) 在本次保护要求提出之前已合并；它使用当时明确的正式发布授权。
- `v3.0.0` annotated tag 固定在该合并提交 `7d5c61f6bd4b656df92298605d78331314029e4f`，不会因为随后添加规则而移动。
- 本页描述保护启用时的实际设置。后续应在合并前再次读取远端保护与检查，不能用这份历史记录代替实时状态。
- 本次规则只针对这个仓库的 `main`，不表示配套 `exam-library` 仓库也已配置保护。
