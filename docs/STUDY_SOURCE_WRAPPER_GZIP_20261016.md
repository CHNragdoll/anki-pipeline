# 2026-10-16 网页原卡页无损 gzip 交付

本轮只缩小网页传输量，保留原卡页、正反面内容、音频、例句/chunk、审核资料和物理计数。没有重建 APKG、修改 PostgreSQL 或写入学习进度。首次立即翻长卡仍以秒计，压缩率不等于打开速度提升比例。

## 实现与边界

公共工厂 `prepare_library` 使用 `write_wrapper_gzip(root, raw)`，为每个成功准备的卡页增加 `evidence/_study_prepared_wrapper_<原始字节SHA256>.html.gz`。文件名绑定解压后的原始字节；gzip 使用 level 6、mtime 0。既有文件必须是普通文件，拒绝目录/文件符号链接和冲突，按原文长度限制解压并逐字节比较；新文件写完后才原子发布。

公共 host 仅在配置明确启用 `wrapperDelivery: source-gzip.v1` 时使用副本。从当前根 index、完整 artifact 和已验证小正面的绑定获取源 SHA；下载解压后，仍执行原完整 wrapper 的 SHA、骨架、双面、base 和 prepared 来源校验。解码成功后的来源不符不能以回退掩盖。旧导出、浏览器不支持解压、gzip 缺失或实际损坏，保留原页兼容路径。取消和邻卡解压后 2MiB 流预算不会触发额外原页下载。

未改 `PREPARED_FRAME_RUNTIME`、原 full/front artifact 或 prepared index。没有采纳并行提前下载、连接后激活词源 iframe或推迟未就绪布局采样等隔离候选；原生、词源、字体和布局完整就绪后才显示背面的门槛保留。

## 三书准备结果

| 书 | 原页数量 | 原始页字节 | gzip 副本字节 |
|---|---:|---:|---:|
| 2027 红宝书 | 6,532 | 800,934,930 | 126,287,827 |
| 2026 红宝书 | 6,682 | 932,879,673 | 159,306,180 |
| 2027 刘晓艳 | 1,960 | 240,445,153 | 53,449,356 |
| 合计 | 15,174 | 1,974,259,756 | 339,043,363 |

prepare 自然退出0，未知 prepared 卡为0。压缩副本总量约为原页17.2%；它们是网页的新增传输副本，原文件仍保留，不将该数字当作 APKG 包大小。三书 gzip 生成分别约100.8、75.9、22.0秒，来源收尾核对另外记录。

## 验证与实际限制

host 的15项合同覆盖精确原字节、gzip缺失/损坏回退、有效gzip但解压原文被篡改的拒绝、旧协议、无解压API、Content-Encoding避免双解压、解压后预算、取消和过期缓存绑定。工厂核对成功覆盖、幂等、冲突/符号链接拒绝及旧full/front/index严格字节不变。独立复核未发现P1/P2。

v14干净wheel安装的133个包文件逐SHA相同，MathJax 25文件及SOURCE、LAN模板和两个CLI真实target导入/help通过。报告 `output/study-catalog-20261015/wheel-current-install-qa-v14.json`，SHA为 `37d4cd0e9a920342671a4e111a0755e3777b081d0969ea817a9f96eee0c2e357`；包源封印 `1d0f11a92d1d30c500bff6515a4905b33f70cc75d7b6217b8437d7391ca35121`。

隔离实际页面使用最终公共host检查了remote、ambition与more，完整背面均可用，remote为4条主例句，ambition为23条及27次物理出现。more仍626条主例句、688次；按`data-ownership-history-id`口径，新旧页面均570个不同ID、1,144份显示副本，native均ready。本轮对照只使用这一明确定义的口径，不把旧报告的578个历史引用与它混算。

最长more原页17,177,302字节，对应gzip为1,870,074字节。初步隔离计时中读取原页/副本均受cache与主机负载影响，完整背面仍约3.6至11.9秒，不能宣称压缩已解决首次秒开。轻量分段记录定位到词源子文档的首段脚本执行前有等待；它的内联源码约32KB，没有外部资源或固定1秒定时器。`inits`实际表示load完成次数，不能误称脚本开始次数。准备好后的翻面仍复用原协议，此轮没有为取得较短计时而删除就绪校验。

Safari一次隔离首正面可见计时为6,935ms，但后续原生AX/截图读取超时，未取得完整背面的可用验收；已关闭本轮临时Safari页，不将它算作Safari通过。内置浏览器结果不能替代Safari或手机实机。

## 部署与恢复材料

源码检查点为`49758dc`。独立stage位于本机`exports/20261015/host-upgrades/source-wrapper-gzip-v1`，保留plan、原入口、来源封印、完整gzip清单和有条件回滚。准备后仅加强了安装完成时目标副本必须仍存在的检查：旧脚本/plan/PREPARED保留，只有脚本及对应封印重签，没有重跑gzip或修改已准备入口；正常安装和link后并发删除拒绝的fixture通过。记录见`missing-sidecar-guard-reseal-v1.json`。

最终stage脚本SHA `b3421c3b2be704d4faa07bf2e664c813986c1fa863755544da2185cb23c02447`；plan SHA `424351c6c8d61e6be028b188199172eb9b1430f29ab0c1c68c69bd8cf1fe59e0`。正式promote退出0，三书index.html/COMPLETE.json共6个入口文件已替换，最终来源复核通过，版本为`study-web-host.v12-source-wrapper-gzip`。HOST_RUNTIME SHA为`ee4c11e575274f9401f4adf086113113d4c53d2754067147da837f222e644cb4`，三书prepared index根pin仍与v11相同。没有推送远端、合并PR或更新Release。

正式三入口实际完整翻面通过：2027 train为45次、native ready；2026 remote为4条主例句、native ready；刘晓艳ambition为23条主例句、27次。三页DOM均确认`source-gzip.v1`、上述同一host资源、`shared`挂载，无fallback提示。证据为`wrapper-gzip-production-{2027,2026,liu}-ui-v1.json`；最新正式统计截图为`output/study-catalog-20261015/wrapper-gzip-production-train-proof.jpg`。当前正式页面保留原目录样式及原网址，已有标签页需要刷新后取得新host；这次内容完整性验收不等于首次立即冷翻性能达标。
