# 共用 chunk 区间表示：实现与接入边界

此模块为网页版和 APKG 的共同生成层准备新表示，目前默认导出、正式 HOST/FRAME、现用服务和发行附件均未启用。
它不是新的词义数据库，也不重新匹配单词、译文或义项。现有 PG 内容、物理次数和学习身份仍是来源。

## 已实现的共同接口

`anki_pipeline.study_chunk_intervals.compile_html` 接收精确 UTF8 字节、调用方声明的句根及独立审校 alignment、外部 source SHA、
已审完整样式的 CSS SHA 和明确的纯 chunk 样式能力。token 流编辑不构建 DOM、不执行脚本、不读取外部资源。
`SentenceBinding` 的 root ordinal 只用于这一份源 HTML 的扫描，不能拿旧 DOM profile 的路径冒充新绑定。

产物包括 compact HTML 和 `study-chunk-intervals.v1`：

- 按唯一来源共享的原文、译文、alignment、codepoint 范围与整句 ID。
- 共享属性、ID 集合、每个新句根／段落的 UTF16 区间及保留节点记录。
- 原字节编辑和词法表，供 `restore_html` 在外部 source/profile SHA 下精确还原。
- 每个未选择根的原字节范围、SHA 和 `unselected` 原因。声明为 canonical 却不一致时直接报错，不改成未选择。

仅删除默认无文字样式的普通纯文本 chunk 包装；目标词、强调、有样式／ARIA／tabindex／未知属性、嵌套或包含元素的包装保留。
输入是保守的 generated-HTML 子集。隐式闭合、表格／template／命名空间上下文等无法证明的情况拒绝；
原共享 renderer 用 `<br>` 表示 canonical 换行的情况目前也不能选为区间根。这些边界要在完整绑定投影中明确保留，不能忽略错误后声称全量覆盖。

`anki_pipeline/templates/study-chunk-intervals.js` 消费同一 profile，入口为：

```js
const handle = StudyChunkIntervals.install(document, profile, {
  binding: {source_sha256, compact_sha256, profile_sha256, css_sha256},
  isCurrent,
  clearLegacy,
  onInvalid
});
```

上述 binding 是调用方已经验证的外部交付能力；相同字符串不等同认证。
runtime 不下载第二套资料，不用 DOM 序列化冒充原字节 SHA。它独立核对 canonical alignment、区间、实际 DOM 和保留属性，
一次建立索引，鼠标／键盘只核当前句根。临时高亮仅拆分和恢复 Text，保留原 mark、ARIA 等元素身份。
`release` 用于反向交接旧 chunk owner；`refresh` 用于显式全量复核；`dispose` 只清理自己拥有的状态。
旧 delegated callbacks 的排除和原私有 clear 仍须在完整接入中显式完成，不能仅插入新 listener。
同一实现 revision 的脚本重复执行复用冻结 API；同一 document 在显式 dispose 前拒绝第二个 owner。
交付中的实现发生变化时必须更新 runtime revision，并由集成层先 dispose 旧 owner、显式换新 document/API，
不能把 schema 相同当作新版代码已经替换成功。当前仅为未交付的首个实现 revision。

## 当前验证范围

首版Python17项、Node19项通过，独立合并审查复现并关闭4个P2。
后续实际HTML解析对照发现实体CR处理边界，窄修后最终Python18项、Node20项通过（根代理wall12.141秒）；
这是测试耗时，不是用户翻面耗时。numeric `&#13;`保留CR，只有literal源CR／CRLF规范为LF；
旧代码实际失败、新代码通过的原记录均保留，runtime JS本身未由这次修正改变。
[源码pin、原始RED/GREEN、独立反例和真实小样](../output/study-catalog-20261015/chunk-interval-shared-v2/ARCHIVE.md)保留本节点范围。

真实 train 固定四根：82 个源 chunk 中删除 64 个，保留 18 个；其余 86 个根保留原字节。
真实 abolish 固定一根：16 个源 chunk 中删除 15 个，保留 1 个；其余 7 个根保留原字节。
两者使用同一 API，逆构均精确等于原 source SHA。这里不是全卡覆盖或速度测量。

Python 专用检查从仓库根运行：

```sh
.venv/bin/python -m unittest tests.test_study_chunk_intervals -q
```

Node 合同使用现有虚拟环境生成真实样本，不能默认依赖系统 Python 的 genanki：

```sh
PYTHON="$PWD/.venv/bin/python" NODE_PATH="$PWD/node_modules" \
  /opt/homebrew/bin/node --test tests/study_chunk_intervals.test.cjs
```

JSDOM 几何是明确模拟的 oracle，不能证明 Safari 字形命中、触摸、查找或实际翻面耗时。
[此前小组件 Safari 记录](../output/study-catalog-20261015/chunk-interval-component-observed-v1/ARCHIVE.md)
属于不同的 pilot schema，不能移作此新 runtime 的浏览器验收。

## 完整生成仍需要的工作

共同接缝是 `project_note` 中 `project_display_fields` 之后、资源 alias 改写之前；
仅修改 web 专用 `_render_note` 不满足统一生成。完整 live／历史根至 canonical 的来源绑定总表尚未实现，
必须复用 source/hash/目标范围、active analysis 和历史链的实际证明，不能从文本或 chunk ID 猜测。

原 compiled profile 的节点路径和属性不能直接复用。普通 span 解包使相邻 Text 合并，新锚也改变属性集合；
需要精确的旧／新局部路径账本，同时保持原 groups、Bank、projection、reader 身份与文本。
新 runtime 动态绘制会触发旧 compiled observer 的 childList 拒绝；后续需要绑定当前 doc/owner/认证 plan 的私有绘制接缝，
逐条核本次精确变更，不能关闭 observer、吞掉整批记录，或凭一个 DOM 标志授权。

只有完整 source/prepared/profile/CSS 认证、原 native／字体／子页／稳定几何门、最大卡 Safari 实测，
以及三书完整 APKG 更新／重复导入与原生设备验收都通过，才能报告这个优化已交付。
# 路径转换检查点

`study_chunk_interval_paths.py` 以流式解析提出原 compiled profile 的路径和新增锚属性变更，
只允许已选段落中普通 chunk span 的完整成对标签删除；不允许删除强调、键盘或未知属性节点。
独立复核复现的可逆 `<mark>` 删除漏洞已关闭；根代理当前运行 34 项 Python 检查全部通过。
该接口只返回转换提案，尚未安装到完整卡片，不构成 Safari 性能或完整导出的验收。
