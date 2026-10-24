# 共用区间模块：小合同及合并审查

这是新共用编译器与 runtime 的本地代码节点；默认导出、正式 HOST/FRAME、服务、PG、真实集合和 APKG 均未由本节点启用或改写。
源文件精确 pin 见 `source-pins.json`，实现说明与完整接入待办见
[共用区间表示](../../../docs/STUDY_CHUNK_INTERVALS_20261017.md)。

- Python：首版17项通过，实体CR修正后最终18项通过；原始小样在 `compiler.tar.gz`，最新原始结果在 `numeric-cr-fix.tar.gz`。
- Node：首版19项通过（根代理wall13.380秒），后续增加实际HTML解析的实体CR／literal CRLF对照，最终20项通过、wall12.141秒。两轮原始日志分别保留，不能把首轮覆盖数字改写成20。
- 独立合并审查：4 个 P2 已实际复现并修复，最终无剩余 P1/P2，原反例和定向复核在 `independent-review.tar.gz`。
  不把重叠的测试次数相加为独立覆盖总数。

修复包括：同 document 重复安装及同脚本重复执行的单 owner、旧 dispose 的 ABA 边界、
Shift+Enter/Space 原行为、实际 physical occurrence owner 漂移、root 160／paragraph 163 字符接口边界。
此前 pilot 的 Escape 后同区间微移重新激活也在此 runtime 中有定向检查。
精确 ID 错位、canonical 表篡改、getter／调用方修改、外部 DOM 漂移、控制按钮、取消和仅局部核验等负例均保留。

根代理有一次 runner 环境启动失败：将虚拟环境 Python 的符号链接 resolve 到基础解释器后缺少 genanki，尚未进入合同。
`root-env-failure.tar.gz` 保留这次原结果。保留 `.venv/bin/python` 路径拼写后，上述最终19项全绿；
没有安装全局依赖或把该错误当作产品 bug。更早一次未设置 PYTHON 的工具输出同样是环境启动失败，未保存完整文件。

真实样本仅选择 train 的4根和 abolish 的1根，其余86／7根逐字节保留并显式报告；
本模块不具备完整 live／历史 canonical 绑定总表，带 canonical 换行／BR 的选择等仍有保守拒绝边界。
JSDOM 字形范围为模拟 oracle，没有新模块的 Safari／手机／完整 FRAME／速度或 Anki 导入验收。
不同 pilot schema 的既有 Safari 观察不能代替这里的浏览器结果。

`compatibility-review.tar.gz` 保留只读的旧 compiled 兼容分析及极小实际拒绝复现：
路径与新锚必须重编，动态 Text 绘制会被旧 observer 拒绝。该报告不是接入代码，也不授权略过原四种语义安装、来源证明或完整门。
所有 tar.gz 只作无损保存，成员 mtime=0；原日志、diff 和原有封印字节不改写。

只读验证：

```sh
.venv/bin/python output/study-catalog-20261015/chunk-interval-shared-v2/verify_archive.py --current-source
```

默认只检查归档；`--current-source` 才额外核对当前四个源文件。验证器不解包落盘、不跑 Node／浏览器／服务或访问 PG。

后续实体CR修正区分literal源换行与解码字符引用：`&#13;`在实际解析中保留CR，literal CRLF则成为LF。旧编译器实跑新正例exit1，修正后18项Python和20项Node均exit0。新JS runtime字节未变；原文精确逆构和旧／新双语交互对照通过。`before-cr-source-pins.json`保留首版源pin，当前四文件使用新的`source-pins.json`。旧本地v1封印`ae3cc287…fd9881`保留，不重写；v2新增实体负例证据与当前源pin。

实体CR增量的独立审查在 `numeric-cr-independent-review.tar.gz`：parse5 8个小对照及新增Python／Node各1项通过，源码差异限定于literal normalization；无剩余P1/P2。它不重跑或追认其他未变矩阵，不证明真实Safari字形或中文反向。
