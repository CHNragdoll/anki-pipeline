# 2027 考研倒计时恢复

范围：本地模板修复（change / local-trial，bug，R1），恢复正反面右下角倒计时。保留此前阅读排版和两列词形。未操作用户 Anki 资料库或远端发布。

## 日期依据

- [教育部 2026-09-24 公告](https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/202609/t20260924_1451846.html)：2027 年招生初试于 **2026 年 12 月 19–20 日**举行。
- [人民网时间安排](https://edu.people.com.cn/BIG5/n1/2026/0924/c1006-40805040.html)：首场 12 月 19 日 08:30 开始。
- 目标使用明确时区的 `2026-12-19T08:30:00+08:00`，不依赖设备所在时区。显示 2027 招生年度，目标是 2026 年实际考试日。

## 行为

倒计时每秒更新，在右下角固定显示天、时、分、秒；到点改为“2027 考研初试已开始”，不出现负数。翻卡执行脚本时替换旧计时器并复用同一元素，页面移除/离开时清理计时器。底部预留空间，使末尾内容能滚动到倒计时上方；读屏不每秒播报。

## 验证

- `node tests/test_countdown.cjs`：北京时区、天/时/分/秒换算、最后一秒、到点、过期、重复加载及清理全部通过。
- 67 项 Python 测试通过。
- 浏览器实际观察到秒数变化，正反面单个倒计时，1280px 和 320px 视口均在右下角且无横向溢出。
- 已安装 Anki 26.9.3 backend 隔离覆盖导入，1960 卡片/笔记及媒体，ID 相同、样本复习进度保留；报告 `output/countdown-verification.json`。未宣称实际 Anki GUI 已验收。

最新交付：`output/Anki-2027考研倒计时版.apkg`；`output/preview.html` 同步更新。完整包校验和与构建记录见 `output/countdown-verification.json`、`output/countdown-build.json`。

![右下角倒计时浏览器预览](../assets/screenshots/countdown-2027-desktop.png)
