# 真实 train 小组件：文本 DOM 与区间交互

这份归档保留一个真实 29 次出现的 panel、其中同段同义的三成员分组及匹配原例句。
四个句根中普通 chunk 标签减少，但全文、目标词标记、三处依据、来源与物理次数保留。
891→827 个元素、82→18 个 chunk 标签，仅是这个组件的测量。
HTML 加新区间资料总体反而增加 19,393 字节，不能宣称包体下降或最大卡提速。

根代理在独立 Safari 窗口使用原生鼠标与“在页面上查找”完成了：

- 原版与区间版同一落点的跨行英文、对应中文高亮；中文反向选择同一英语块。
- 点击句外和行末空白清除高亮，未错误选择最近的字。
- 收起的三处审核中查找“目标位置 3”，Safari 报告一处并自动展开审核。
- 查找跨原标签的“owns train operator Trenitalia”，Safari 报告两处。
- 2021 筛选显示 5 条，恢复全部显示 27 条合并原文，物理次数仍为 29。

详细观察在 `safari-observations.json`。工具中看过截图，但没有落盘图片；
这不满足最终 README 详细截图交付，也不是完整 FRAME／最大卡／Anki 设备验收。
触摸、笔、缩放、真实键盘目标、取消与错误 UX 等仍未做真实浏览器验证。

本次看到一次 Escape 后原处高亮未消失，未采集浏览器事件，不能推断原因。
独立的小事件配对复现了一个确切差异：Escape 当下两版都清除，随后同块 pointermove
会使候选再次激活，原版不会。`escape-review/` 保留八个配对序列；
新共用 runtime 必须处理该差异，不能把这版小组件直接推广。

`pilot-files.tar.gz` 无损存放原封印的 62 个成员及 `FROZEN.json`，
所有成员字节和原封印保持。解包到新临时目录后，小合同可用既有 Node/jsdom 单独重放；
不得重写原临时封印目录。19 项历史小合同不包含新增 Escape 后微移序列，也不证明浏览器性能。
`server/` 保存启动清单、ready/requests/closed 原始记录。服务只绑定回环，已退出并排空，
38 项已使用的资源收尾复核相同；工具输出出现关闭 keepalive 后的 ConnectionResetError，
完整 stderr 未保存，不能称作无错误运行。专用 Safari 窗口已关闭，未操作用户原窗口。

从仓库根执行：

```sh
.venv/bin/python output/study-catalog-20261015/chunk-interval-component-observed-v1/verify_archive.py
```

验证器只读本归档，不解包大文件、不打开浏览器、不启动服务、不重跑渲染，也不改变 PG 或 Anki。
