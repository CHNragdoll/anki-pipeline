# 原生 Browse／Preview 后台对照

用户报告前台测试再次卡死后，已关闭那个自有隔离进程。本次没有再次要求用户手动测试，也没有打开正式个人集合。使用安装的 Anki **26.09.3 (29bb700b)**，独立完整数据库／媒体副本、原生 Browser 和 Previewer、`QT_QPA_PLATFORM=offscreen`，每次仅自有进程组最多运行 45 秒。

本次副本继承[已逐格核验的索引统计更新](../native-index-statistics-20261018/README.md)。这不是对实际用户集合执行维护，更不是证明更改 APKG 即可替目标集合更新统计。

## 已观察到的结果

| 场景 | 实际观察 | 边界 |
| --- | --- | --- |
| a，原始约 9 MB 字段，单独验证 | 原生编辑器加载及字段检查完成；正面外层 ready 后执行原 Preview `_on_next()`；背面外层于 **4.865 秒后**首次 ready | 单次后台结果；采样间隔最终约 380 ms；没有可见窗口或绘制验收 |
| a 完整背面 | 同一 canonical id，generation 1→2，`answer=true/ready=true/state=ready`；3513 个 `.sf-example`、15 个义项、516 个 details | 不是只观察内层 payload ready；没有切到另一张卡 |
| abide | 背面外层 ready；待核对例句与有次数义项均点击展开；2012 年筛选后仍 ready，状态为“显示 1 条原文” | [此前对照](abide/REPORT.json)中 a 背面只见内层 ready，后来切到 abide；该次不能用作 a 的完整背面证据 |

`a` 的 **16.256 秒**是启动脚本后的累计时间，包含应用和编辑器初始化；不能把它当成翻面时间。正面首次 ready／原按钮请求在 11.391 秒，背面首次 ready 在 16.256 秒。Qt 心跳持续，最大相邻间隔约 1.09 秒。

## 诊断工具本身的错误

在首次真实外层 ready 快照后，诊断 terminal 记录器出现重复 `elapsed_ms` 参数的 `TypeError`，未写出预期 TERMINAL 文件。因此不能将本次称为“整个 harness 无错通过”。原始快照和时间戳仍保留在 [events.jsonl](a-only/events.jsonl)，[摘要](a-only/SUMMARY.json)和[完整报告](a-only/REPORT.json)明确保留该错误。父进程按原 45 秒上限结束自有进程组，最终无残留成员；未为凑通过而重跑或放宽上限。

源关闭数据库、原 APKG 中的 a 字段、源媒体目录及安装代码 pins 均保持；测试编辑器对私有副本发生的原生 HTML 规范化单独记录，不能宣称副本字段逐字不变。此前索引更新的 notes/cards/revlog 逐格相同结论只对应进入编辑器之前的两个库。

## 索引来源已核清

`idx_notes_mid` 来自 Anki 标准 schema 15 升级，不是本项目额外创建。安装版新建空集合、从未导入 APKG 时，已经存在该索引而 notes 统计为空。[空集合实测](standard-index-origin.json)和 matching [官方升级脚本](https://github.com/ankitects/anki/blob/29bb700b/rslib/src/storage/upgrades/schema15_upgrade.sql)支持这一点。普通 APKG 导入不搬运源索引或 `sqlite_stat1`；删除源包索引不能解决目标库问题。

## 仍未验收

真实 Cocoa 窗口、用户正常 Browse／Preview、手机、全部卡片及音频交互均不由这些结果证明。当前 v4 也未包含后来提交的浏览列表模板回退，不能作为新完整交付包发布。后续候选仍须正常统一生成及内容、学习状态、原生导入和实际界面验证。

[复制文件的 SHA 与范围](evidence.json)；原始私有全量副本保留在各报告指向的位置，未纳入 Git。
