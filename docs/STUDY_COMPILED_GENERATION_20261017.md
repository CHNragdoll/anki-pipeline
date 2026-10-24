# 共同完整卡片生成：语义和交互资料接口

已接受的完整渲染路径继续在原入口使用。本次整理的是生成端，不重新设计浏览器交互协议。

`study_compiled.build_semantic_request()` 校验完整源 wrapper、payload、两面、registry、作者资源策略及原生模块的精确派生关系，再把实际用到的脚本冻结到新目录。
`compiled/semantic-producer.cjs` 只读取这些显式本地资源，执行原 Fine／Projection／Bank／Group，输出既有 keyed HTML 和 `study-canonical-interaction-bindings.draft.v1`。
没有按书名、年份或单词选择另一套算法；只接受两种已有审查记录的模块能力，未知输入明确拒绝。

`build_profile_request()` 从同一成功语义结果校验来源，构造既有 17 项外部绑定，
并冻结原历史片段和 AF 审核证据。`compiled/profile-emitter.cjs` 沿既有 AST／stream 路径输出
完整交付 HTML、`study-compiled-card-interactions.v1` 和 anchors；只在实际缺少逻辑根 key 时
插入明确的 key 属性，并证明逐字可逆，其他来源和计数不改。

审核证据有两种原存储位置。原片段中的依据继续使用已认证的 history slot；
初始句子里直接引用 AF 的依据在语义生成前按原媒体的 raw SHA 和完整原文 SHA 核验，
提前填入完整原文并设原加载器的 ready 标记。生成证明保存原占位文字、属性和逐节点逆构。
交互资料生成器再次核对 ready、纯文本、原媒体及受保护根；单设 ready 或未知引用不能通过。
原加载器会跳过这些已完整的依据，现有交互运行时继续保护完整文字和属性，不引入另一套事件协议。

helpers 保留成功 pure producer 的原适配算法字节，并追加当前共同 FRAME 的原作者脚本收集器。
收集器校验脚本来源和顺序；语义阶段不执行作者的视觉启动代码。构建需要项目现有 Node.js、jsdom 和 parse5 环境，APKG 用户不需要运行这个构建工具。

## 已取得的实际证据

- 当前 PostgreSQL revision 14 的三书各一张 `abolish` 经 `project_book/project_note` 和原共同渲染器重建，与现用三个源 wrapper 逐字相等；这是三个样本的来源核对，不是全书核验。
- 真实 2026 `abolish` 已联合调用 Python 请求构建器和新 Node producer。4 次出现对应 4 处 SF 与 4 处下方例句展示：8 处原句和译文全部相等，4 个审核节点及其文字保留，15 个脚本节点保持原顺序及原 DOM 内容。
- 同一完整背面含两个相同原生模块引用，只执行一次原生模块；原四语义捕获与 5 个实际 handle 都就绪，作者视觉启动次数为 0。
- `abolish` 样本没有合并组或 Bank 记录。另一次真实 2027 `train` 使用第二种已审模块：88 处展示原文及译文相等，64 个审核节点及文字保留；1 组三成员合并、2 个 Bank 记录和 2 个关闭的历史槽保留。`original_rendered_rows` 是 DOM 对账数量，不能用于词频统计。
- 新输出的 keyed HTML 和 draft 与首个成功结果逐字相等。两次成功调用记录为 1.965／3.401 秒，均为生成端耗时，不是 Safari 翻面速度或稳定上限。

文件输出保留跨块 UTF-16 代理对，补齐短写，并以不覆盖目标的方式发布；异常输出不能作为成功产物。
早期失败和旧报告保留各自源码摘要。旧报告的 `original_physical_rows` 名称实际指展示行，本次公共接口已纠正名称，不改物理频次。
独立审查发现的 UTF-8／短写／输出文件归属问题已修复并定向复核。隔离 wheel 已确认包含相同的 Python 接口和三个 JavaScript 构建文件，未安装或发布。

## 交互资料与完整审核证据的联合验证

共同 Python 请求构建器、真实语义 producer 和新 profile emitter 已在两张真实源卡上连续调用。
`abolish` 输出仍为同一份 55,724 字节交付 HTML 和 17,505 字节 v1 profile；
`train` 保留 88 处双语展示、64 个审核节点、1 组三成员合并、2 个 Bank 记录，
输出 391,424 字节交付 HTML 与 224,663 字节 profile。展示行数与 profile 字节均不用于词频计算。

联合复核先发现初始句子中的两处 AF 引用未被原 history-part 授权覆盖。
仅拒绝这种输入不能算完成真实 `train`。最终实现提前装入这两处完整原文，保留精确来源和逆构；
另外两处原 AS 槽中的 AF 继续沿原协议处理。当前 e56 运行时已在真实派生 DOM 安装、校验和 refresh：
初始两处原文 SHA 相符，执行原 history 函数确认 ready 分支不读取资源或改写 DOM；
原 AS 两段经实际原 decoder 转换后，通过原 `authorizeHistoryPart/Text`，总共四处 AF 文字完整。
合并、panel、projection 和 Bank 的运行时统计前后一致。未运行作者视觉启动或将此当成 Safari 翻面测速。

39 项定向测试通过，覆盖假 ready、错误正文、缺失来源、闭合槽范围、原 AF 媒体、
节点根保护、字节写入及不覆盖发布。本节点隔离 wheel 另核对全部 7 个构建资源与源码逐字相等，
未安装或发布。完整证据保存在
[共同 profile 生成记录](../output/study-catalog-20261015/compiled-profile-product-v1/result.json)。
这份运行时验证仍不替代实际 Safari、手机 Anki、全量新包与最终包体积验收。

## 尚待接入

1. 在共同字段投影后生成一次派生结果，交给网页和 APKG；原生客户端还需要本地资源及当前卡 owner 的 bootstrap。
2. 实际批量核三书全部内容、身份、计数、媒体和包体积，再验证浏览搜词预览、正常复习及真实页面交互。

实际刘晓艳样本没有声明四语义模块，本接口拒绝把它冒充为可编译输入；现用原完整渲染保留。后续共同 factory 须按内容能力选择适用处理并记录覆盖情况，不按书名选择算法。

本次没有改变 PostgreSQL、当前网页、真实 Anki 集合或 APKG，也没有更新远端发行。
当前网页采用范围仍见[完整渲染采用记录](STUDY_COMPLETE_RENDER_ADOPTION_20261017.md)。
[实际样本、源码摘要和测试记录](../output/study-catalog-20261015/compiled-semantic-product-v1/result.json)
分别记录本阶段的生成、来源对账、独立审查及安装资源覆盖，不能替代完整导出或客户端验收。
