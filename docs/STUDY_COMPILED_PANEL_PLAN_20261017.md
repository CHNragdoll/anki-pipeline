# 生成阶段语义处理与显式新交互绑定

## 最新最大卡实测与已排除的重复工作

2026-10-17电脑Safari的冻结profile复用候选，首次完整正面1,872ms、立即请求完整背面7,419ms，
原完整几何／字体／子页门通过，提交后compiled句柄invalid为null。此为一次不受控样本，未达到秒开，
不能把它与前次11.808秒的差额归因于该候选，也没有替换三书正式入口或APKG。
[紧凑证据](../output/study-catalog-20261015/compiled-card-largest-frozen-profile-v1/observation-summary.json)
保留原始下载、24项来源pin、18项QA pin和可逐字重建／逆验材料，未复制49MB正文及22MB profile。

该候选避免再次JSON序列化及复制已认证、深冻结且仍属当前owner的profile；未知或可变输入仍走原逻辑。
小合同与独立审查通过不等于已实测内存收益。下一项只读核对发现，2,032ms的batch中首次真实几何读取占1,943ms，
其余同类读取合计约1ms；完整门已在同一rAF检查全部子页，并非逐个串行等待。
因此不再以合并几何读取或并行等待为名生成无证收益的小补丁，完整标准保持。

## 屏外排版的小型实测：拒绝直接估值方案

2026-10-17，Safari 27 在[独立64行小页](../output/study-catalog-20261015/qa-cv-find-20261017.html)
实测`content-visibility:auto`及72px intrinsic估值。普通Cmd+F、闭合details原生查找自动展开定位、原生fragment跳转
均成功；两种模式保留339个节点、64行和同一正文校验值。此项只证明小页的原生交互能力，不证明真实大卡性能。

原版完整body高度为16,232.4px；CV在屏外及移入后均可通过三次稳定检查，却只有8,138.8px，61行仍被跳过排版。
依次原生查找、展开、跳转后，CV高度又变为9,049／9,914.3／10,555.3px。因此现有完整几何门可能只确认了占位稳定，
不能直接把该样式加到真实大卡并宣称完整就绪。此直接估值方案不采用；不推导为所有CV算法不可行，也不弱化原门。

[原版实测](../output/study-catalog-20261015/qa-cv-native-baseline-20261017.json)、
[CV实测](../output/study-catalog-20261015/qa-cv-native-auto-20261017.json)和
[证据摘要](../output/study-catalog-20261015/qa-cv-native-evidence-20261017.json)保留实际输入、浏览器与原生操作范围。
仅新增小页，未改正式三入口、FRAME、总库或APKG；自有Safari窗口已关闭。

这是统一总库／共享生成工作的性能后续，不另建数据库，不缩小为只让小卡可用。
分支为`feat/unified-study-database-20261015`；基线共同源码SHA为`caf263d17768d63a0f3fc01813f8204b8b44b23f63414b6ab69f273692177b3d`，
FRAME为`c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02`。
正式三个入口保持此前206版本。前置迁移／恢复证据继续有效，本计划初阶段不写PG、APKG、媒体或真实Anki集合。
实现已由用户授权；此计划不授权远端推送、PR、合并、发行。

最大卡v3已在真实Safari通过原完整背面门并观察到compiled句柄；未加时钟7.642秒、phase页7.775秒、claim v2页7.117秒、layout诊断页7.197秒、resource-proof页11.808秒，仍未达到性能目标。
返回正面48ms、重复背面149ms是早先未加阶段时钟的v3页面单次观察，不是冷缓存、绘制完成或稳定上限证明。
本次Safari仍用冻结旧HOST，正式入口与PG／APKG未变；共同产品源码加载接缝另有未发布改动，尚未接入此次compiled FRAME。
下方旧记录保留各自当时范围，最新resource-proof的重复复核消除及不受控整卡样本见文末；早期编号或校验区间缩短不能单独当作整卡净提速。

## 最终目标和设计边界

所有既有内容、用户可见功能、计数与身份保留；完整背面在准备好后一次提交，切卡／翻面达到秒级且不卡住主线程。
新书、新学科仍通过总库映射和同一生成逻辑，不能为书名／年份／单词增加专用渲染分支。
小卡原型是证明方法，不能作为全目标完成；最大卡和三个书籍投影最终必须实测。

旧的Fine v2输入图重放在大卡上超时，不继续扩展该协议。编号延期一次大卡仍为10.970秒，不作为完成方案。
新profile明确把可确定的语义计算移到生成阶段；浏览器只验证来源／metadata／派生产物绑定并建立新运行期交互。
不能把postHTML加SHA说成恢复原WeakMap、Text或undo，也不必伪造旧私有handle身份。
新handle必须有明确的refresh、取消、dispose和外部修改保留规则，并与原用户操作逐项对照。

关闭正文首先留在真实DOM。Safari实际小样例可查找关闭details，但查不到未插入template；
任何减少闭合DOM的后续方案必须先证明原生查找／自动展开／定位等价，不能用文字镜像或半张卡替代。
词源iframe、音频、字体、原文跳转、倒计时及完整布局门保持可用，不能因语义编译而默默退出。

## 执行顺序与证据

1. **真实原算法producer。** 在完整2027 abolish小卡上下文执行同一固定canonical Fine／Projection／Bank／Group；
   输入、模块、适配、metadata与范围验证分别封印。记录实际成员身份／顺序、中英文、target／chunk范围和审核归属。
   先在`/tmp`执行，重用固定依赖及已有harness；可把纯语义阶段和视觉阶段明确分开，不用假native ready。
2. **新绑定协议。** 根据真实事件消费者固定最小产物格式和浏览器binder；稳定身份使用原occurrence、mapping及位置，
   不凭文本相同判断归属。先保持全部正文DOM，避免把原生查找问题混进状态验证。
   refresh处理新增／外改内容的规则必须明确；dispose仅撤销自己仍拥有的值，不覆盖外部写入。
3. **有意义的原／新对照。** 四句abolish覆盖原生细块／整句及Projection，另加同段同义可合并的真实成员，
   不能用四句互异样本代替合并正例。核全部／年份筛选、编号、chunk点击与键盘、翻译／对照、审核、来源跳转，
   展开／收起／再展开、重复refresh、取消、换卡和dispose；错误位置、成员缺失、范围漂移、旧异步返回须拒绝。
4. **独立审查和真实Safari。** 只围绕实际新diff、格式、用户操作和风险集中审查；通过后做隔离小卡及最大卡。
   记录首次选卡、立即完整背面、重复翻面和切卡耗时，同时核可见完整内容及原生Find；不靠加长原超时或跳校验过门。
   如果完整门／保真／净成本失败，保存反例并修实质问题，不以一个green fixture宣称提速。
5. **共享生成集成。** 仅在新profile成立后接统一factory；全量核三书及跨学科投影、全部保留字段和计数、稳定note/card/model/deck ID，
   对受影响的真实客户端行为先做最小验证包再更新完整包。内容／媒体／学习记录保留，包体积不得因大份运行时输入图反弹。
   产品fallback必须按能力和输入格式处理，不能按某本书／某年份切两套业务逻辑。
6. **交付。** 全量生成和安装／实际UI范围匹配后，再条件推广三个原入口、更新README截图与状态、提交关键Git。
   发布只在用户另行授权后执行；总目标仍以原计划完整审计为准。

## 本阶段停止线

纯语义producer、数据格式或小卡binder通过都不代表秒开；不得将构建时信任边界冒称浏览器仍独立重复全部语义。
如实际交互有差异，先固定负例。若小卡净成本已明显大于原路径，不先推广大卡或三书。
第一里程碑是一个真实小卡原／新完整交互和成本可评估结果，不是最终验收范围。

## 首个真实小卡完整宿主结果

2026-10-17电脑Safari、同一LAN原源资源，隔离新页使用独立编译profile。
FRAME `e1263627e216f9fa109056a2223f62711a8e5d545a8cc6eda93ee279cfc85a08`，
新binder `e559bd68401cb16fb0a2ffaba60aeca11bf76dffc25d0880a9873e1223042dc9`。
十处宿主编辑逐字逆回c7；未修改原10秒／完整布局门、child/Cigen、字体、媒体或倒计时。

| 当前abolish小卡的实际操作 | 浏览器父页面记录 |
| --- | ---: |
| 新页首次完整正面 | 972ms |
| 正面完成后立即请求完整背面 | 310ms |
| 手动翻回已准备正面 | 28ms |
| 手动再翻已准备完整背面 | 4ms |

这是一次完整提交信号的样本，包含消息传递，不是绘制完成时间、无缓存保证或稳定上限；
历史314／438ms样本的观察工作不同，不能将本次310ms描述为相对它们的已证净提速。
两次明确点击的提交后结构检查均为8个原文位置、4次物理出现，唯一新handle的invalid为null。
真实展开后全部4条、2007年2条，恢复全部仍4条；收起义项后，原生Cmd+F精确设置“废除奴隶制度”，
Safari命中2处并自动打开原义项。另一处命中在词源例句中；不能把2个匹配算成新增物理次数。
查找结束后的新handle仍有效，8处原文未丢。自建QA标签页已关闭。

原始浏览器下载`compiled-card-small-v2b-safari-v1.json` SHA
`fa8da39c99f723997bdba8939cf09e55bb995d944b2f722fde970be18d42680b`；
`compiled-card-small-v2b-ui-observations-v1.json`是原生CUA观察的人工记录，不冒称浏览器遥测。
两份保存在`output/study-catalog-20261015/`。

生成端执行的是原固定完整作者序与Fine／Projection／Bank／Group算法；新浏览器侧明确建立自己的交互状态。
原script字节／顺序、payload／manifest、iframe与原倒计时占位保留，只覆盖确有变化的三处语义区域并记录原生分组CSS。
abolish的8个最终原文HTML／文本与之前实际Safari oracle逐字相等，仅明确移除新增绑定key再比较；
train另有3次物理出现合成1条、三个target／三份审核与两条Bank标签的生成及新旧闭包交互证据。
实际旧闭包与新binder的abolish26／train50个快照相等，包含原reader两种模式及MO投递后的合法交互。
完整新宿主组合还证明旧四模块安装0次，新binder与原Residual两个真实handle完成就绪；
取消与ABA旧owner返回不写ready。宿主、binder、slotless适配的合同和独立复核不替代本次真实Safari，也不扩大到全部客户端。

### 当前仍未通过的门槛

- 初版编译宿主严格只接受无Slim manifest的输入。train的两段原closed-history slot保留在原路径，
  未删除，也没有通过compiled宿主完整验收；后续必须接回原按需历史加载及校验。
- 独立复核有一项扩展前P2：在已绑定root以外追加新的原文sibling，当前观察与refresh不一定拒绝。
  已有成员和位置校验通过不代表任意语义区域变化都已覆盖；补区域成员负例前不推广共同源码。
- 最大the、其余两本书、实际连续切卡、音频／手机／Anki完整包、包体积及学习身份保留尚未由新profile证明。
  当前真实小卡没有替换正式入口或产品生成器，没有PG／APKG／媒体／学习记录写入。

下一步是补区域成员边界，生成真实最大卡并测其净成本；仍以全目标完成为最终验收。

### 区域成员边界修复的后续记录

v2c runtime `b3ea07cc22c772c1ac0289c7068658159ad9b00b0daf19fed7f8919a83369546`
用四处可逆修改补齐已绑定root之外的成员结构检查，包含原先没有绑定key的原文行；
以实际节点身份／父节点／原key为基线，不按文本合并。新增、删除、整区／外层替换、重排和新lazy反例先红后绿，
五项定向合同及独立复核通过，原reader、筛年、脚本和页脚合法变化保持。
实际完整作者小卡normal回归另跑一次，8个原文HTML／文本相等、新native ready、2handles、旧四install为0。
此修订保留原profiles；已单独归档到`tests/fixtures/experimental-compiled-card-v1/boundary-v2c/`，
没有替换上方实际测过的v2b字节或把310ms样本算成v2c实测。
原始回归与封印见`output/study-catalog-20261015/compiled-card-boundary-v2c-v1/`。
修复结论限定于区域成员结构，不代表任意外部修改或history slot均支持。

## 共同生成器的实际接点

代码只读核对表明：`study_catalog_export.project_note()`是APKG和web共同字段／模板投影，
有效修订另由`study_catalog_revision`核对当前analysis；PG已有sentence、physical token/range、alignment chunk、
sense decision和完整record／occurrence对象，不只是raw快照。
现有`study-prepared-card.v1`则是`study_catalog_web_materialize.prepare_library()`的web后处理JSON，
APKG并不消费它；不能只把新profile挂在这条web路径，就声称双端统一。

后续在共同`project_note`有效投影之后增加共同派生准备层，供两种包装器消费。
采用内容／输入版本寻址的语义核心缓存，并以精确wrapper／payload／side／模板／依赖／renderer pins另作交付绑定；
不以书名、年份或词头决定算法或缓存命中。根索引应直接声明新compiled主交付，
避免正式用户先取旧大包再多取一份新表示。原source证明、审计和媒体仍保留。
已有SHA对象存储和generated资源管道可复用，但没有现成semantic cache索引；
当前export是只读事务，不能为缓存顺手写入PG。本段是实际接点与待实施方案，不是新的迁移或共同接线完成声明。

## 最大卡单次构建的实际终态

2026红宝书the的完整作者启动构建只运行一次，原定900秒上限未延长。
真实native hydrate于825.847秒返回，五个原handle的断言通过；893.13秒前写完三类成员证据。
15,260处原文的英文／中文SHA与原节点身份全部相等，9,536处原审核节点身份与正文保留，
15,260条target／chunk记录完整写出。Projection errors为空不等于浏览器性能验收。

外部监控在903.17秒触发期限，903.72秒回收进程（returncode -15）。
最终HTML、profile、anchors及完整report尚未生成，终态为`INCOMPLETE_NO_COMPILED_PRODUCT`；
不得将已完成的语义检查或部分文件当作可用编译卡，更不能从构建耗时推断翻面耗时。
小型原字节归档为`output/study-catalog-20261015/compiled-card-largest-incomplete-v1/`，
manifest SHA为`7563fdd1a698367c768befc2c566fb316f296f0053bbb305db99b105570e874d`。
完整大ledger留在封印stage，归档记录各自路径、SHA、字节及行数，没有把近99MB原始输出加入Git。

下一项有界验证按原计划分开语义与视觉初始化：先在真实train上执行同一原decode／Slim／索引／metadata及
Fine／Projection／Bank／Group，对照已有完整作者88处原文、target、chunk、审核和分组。
全部原作者脚本仍须逐字按原序恢复到交付内容，由浏览器实际执行；这不是删除视觉或交互功能。
小样本的等价证据成立前，不重复最大卡，也不修改正式三个入口。

### 后续发现：测试装载器的live NodeList错误

后续train纯语义对照发现，部分旧Node harness使用
`Array.from(parsed.body.childNodes, n => doc.adoptNode(n))`，在遍历live NodeList时移除节点，
可能跳过相邻顶层节点。限定检查找到9份旧脚本／18处该写法，涉及此前small／train完整作者producer、
最大卡单次构建及部分replay／旧闭包harness。因此它们的完整head／body采用声明不能成立；
已执行的作者代码数组、保留行证据和完整源节点采用必须分别判断。
原冻结文件、原失败与日志不改写，不能把旧记录当作已修版本的完整宿主证明。

正式FRAME使用`for (const node of Array.from(...childNodes))`静态快照，无此具体错误；
既有真实Safari观察仍只证明当时的实际输入，不因这个Node测试缺陷自动变成虚假观察。
新的train纯语义v2先取静态快照，逐节点核decode／adopt／hydrate三个阶段的原16个script仍连接且次序一致。
该修订实际exit 0，88处双语与target／chunk、64处原审核、同义三成员及两个闭合manifest保留。
其呈现差异明确是原作者尚未执行的编号、reader／tappable和倒计时，不将这些差异任意剥除后冒称整页一致。

### 历史正文协议与首次train实际Safari失败

两项精确历史part的插入前认证和原AF校验／重试已加入独立原型。
复核发现外层owner取消后旧toggle／排队任务仍可先写loading或启动AF，后续owner-v2以共同入口检查修正；
三条真实反例先失败后通过。原runtime／profile／parts不变，18项相关portable合同通过，
另有独立三反例复核及6项组合／静态采用检查。
归档位于`tests/fixtures/experimental-compiled-card-v1/history-slots-v1/`；这些都不是完整作者序的浏览器验收。

首次实际Safari隔离train使用FRAME `71ca882a5d107d928c8a7fbcb6ba5e6c53d5c1244e8d2bba618e0598c6d6b9a7`，
原严格完整门不变。正面完整信号1272ms，立即翻背面被
`Compiled card invalid: text source-01167`拒绝，背面没有完整提交，不能给出其提速或通过结论。
该key位于2007年转归句的审核区，正在定位实际文本差异，尚不能认定当前句本身丢失。
原下载已逐字保存在`output/study-catalog-20261015/compiled-card-train-history-safari-failed-v1.json`，
SHA `7659eab0c28108d5545a774e1fe5accbecb23027a0d6af839dc5f1da027adfda`。
这次只新增独占QA资源，没有替换正式三个index或产品源码，也没有PG／APKG／学习记录写入。

### 第11个宿主编辑后的实际结果

逐阶段诊断证明原`stageStaticHistory`将两项已加载的静态SF审核转入Fragment，
`source-01167`从11,589缩为251个UTF-16码元；原后置restore恢复同节点和全文，但native失败已经发布。
只在已认证compiled分支令`history=null`，原legacy条件、后续可选调用、完整门和10秒上限均保留。
此第11编辑及原10编辑均可逐字逆回原FRAME；独立复核未发现新增P1／P2。
真实完整作者链控制保持全文和节点连接、old four installs为0、native ready、invalid为null。

最大构建停CPU后，电脑Safari在FRAME
`d4a7ace6aa95f91c17d71c9ac73b137d09508bdc52ecf2ed8c3a344e769a308f`的新页测得：
首次完整正面1279ms、立即完整背面440ms，手动回正40ms、再背98ms。
浏览器资源可能已有缓存；父提交信号不等于绘制完成，单次样本不证明冷缓存、稳定上限或最大卡秒开。
运行时e56／profile639d／bodybf29／owner adapter d9f字节与前一候选相同，只修正了宿主搬移冲突。

按钮后的真实当前状态为88个原文主行（45个SF＋43个主原文）、2个既有原译分块对照辅助节点、总90个example根；
辅助节点从认证derived HTML起便存在，不能把90计为物理词频。词频为45，group为1／3成员、Bank为2，invalid为null。
两项原manifest均loadedParts=totalParts=1、state=ready；两个原AF证据ready=true且各4202字符。
最终原始下载逐字归档`compiled-card-train-dom-preserved-safari-v1.json`，
SHA `add42c7be48510c49249d42233d0afb4d38b662fb20d3e88c209f293760fb163`。

另一次同FRAME功能操作实际看到火车义29次合并为27条展示、2026的18次合并为16条；三处依据分别保留。
两处转归正文及原HTML可展开；第二原part本来没有第一项特有的“原界面的完整审核说明”，不能据此判缺失。
原生查找精确设置“训练受试者”命中3处，下一匹配自动打开训练义项，再下一匹配打开其审核正文。
这些UI观察是人工操作记录，不冒称下载JSON独立测得的查找或交互遥测。

### 最大卡纯语义构建完成，不代表浏览器验收

新单次纯语义run按原900秒／默认heap上限执行，未运行视觉作者startup，未重跑旧已失败方案。
原hydrate于777.451秒返回，844.969秒完成最终HTML，845.898秒写report，854.151秒完成cleanup，
进程自然exit 0；没有延长期限。最终HTML为49,361,493字节，
SHA `3cb5b2191a0b6e2bd851d95eae4700f3f94ae774e2ddf7d4d0a8096b248089c4`。
15,260原行、9,536审核身份／正文检查通过，1,800个组保留4,303成员，隐藏2,503重复展示位置。
这些是生成证据；terminal HTML仍须可逆导出为原始宿主scaffold上的初始交付输入，再构造准确的新profile。
未将最小capture草稿或terminal私有状态当作可部署产物，也未进行该新输入的Safari性能验收。

### 最大卡交付输入、定位信息与首次实际失败

后续可逆导出覆盖全部10个活文档区域（8个SF、词频区、原文区），保留15个原script的raw字节及顺序、
原payload、词源iframe和9个audio节点。源scaffold上的交付SHA为`d9f22ea39e5a60e93d5008918f77022e64adbd848a0c15153044528577329b8f`。
轻量AST发现739个缺少显式logical-root key的原文li；仅添加精确锚属性后的新输入为49,390,547字节，
SHA `61118e38075f73091456ad2964c52e0393b5abdfa89989a417165f12cebfbbe3`。
逐项去除新属性逆回d9f，再按原区域/CSS逆回expanded ddbf；原冻结件未修改。

标准HTML的轻量AST一次完成，未再次执行语义或大JSDOM，生成16,928个绑定、965个reader、14个panel、
1,800个group和201个Bank记录，全部8个活SF区域及原文区域被覆盖。首次profile为22,462,511字节，
SHA `6332cb46de5f23628923292572382128feda74c9e02719e9ebb7b1b23e1ca37a`。
独立审查另复现输出工具的两次读取竞态；新工具在复制时核实际字节SHA，反例通过，
相同输入重组后的profile/anchors逐字不变。原工具缺陷记录保留；此修订不代表浏览器通过。

电脑Safari隔离页首次完整正面为1692ms，自动请求的完整背面被
`Compiled card invalid: bank binding`拒绝，背面耗时为null，不能称为提速或完整交付。
原始下载逐字保存为`output/study-catalog-20261015/compiled-card-largest-bank-failed-safari-v1.json`，
SHA `1d5dd8e9a15fafc5b2aafcd8bc06735b3af5d01731d5eecc54e125c7a536ff8a`。
定位发现：最大producer的201项`compiledAttributes`为属性pair数组，而已固定v1消费者按属性对象读取，
因此第一条会错误读取名为`0`的属性。原label/evidence/requiredAttrs仍在，正在统一生成表示；
不能删Bank、放宽校验或用小卡成功替代这次实际失败。

Bank已在共同v1出口规范为属性对象，201项逐一核对原requiredAttrs/evidence，其余所有profile值保持；
新profile SHA为`34410f5681e22620350b35b8c6d18d753745d89ce5a929e77b7675607252cdcf`，
HTML、e56 binder及11处宿主逻辑不变。原失败小片段与原消费者条件独立验证旧数组拒绝、新对象通过。
转换工具的实际读取快照校验也已补齐，重新生成的profile/anchors逐字不变；不将修工具与修产物混为一项。

第二次真实Safari隔离验证的完整正面为1768ms，Bank校验后在`text node-0009951`处失败，完整背面仍为null。
原始下载保存在`compiled-card-largest-text-failed-safari-v2.json`，
SHA `683411fd873c27ba113e168d2754aab9e4dd21cc8d035c0a60f57a8cc41cafe0`。
该绑定为2025英语一Part B选项B、第43题的原文LI，保存的整行文本以旧序号487开头。
正在用原编号作者和失败realm的有界只读诊断核对实际差异；尚未将其认定为唯一编号差异，也未放松正文保护。

随后父页仅在该错误后读取已认证、仍current的失败realm目标，未改FRAME、binder、profile或原完整门。
Safari捕获该LI完整280字符，实际index-tag为485；与profile保存值逐字符比较，
唯一差异为索引2的`7`变为`5`，原句、译文、来源、Bank文字其余全部精确相等。
原始下载为`compiled-card-largest-numbering-diagnostic-safari-v1.json`，
SHA `4c67bebe2cd54636fcf38c7d09af2c9b94784d843cf5f15a10d06b0f997106f3`。
另以准确原起始标签骨架和完整目标LI运行原9d编号IIFE，小DOM对照同样487→485，dispose恢复487，
全部元素身份/属性保留。该因果已获实机支持，下一步是按原规则准备派生编号并同步整行保护文本，
而非删数字或豁免整个原文LI；其它行及修后完整背面仍须另验。

### 最大卡编号准备与v3实际完整背面

编号准备已按原`9d154…`作者的实际规则，对5,794个合格主原文LI中的5,540个合法badge Text位置做精确派生更新。
未知来源、样式、结构及非单Text的badge拒绝处理；未剥离数字、删除正文校验或改写原编号脚本。
新交付HTML为49,390,544字节，SHA
`746ce538774979ca1108ba5b3233ae5871a3f0ee6d5e232fb93a65b9f7af68cc`。
原位置修改可逐项逆回61118，再逆回d9f和原expanded ddbf；其余字节、15个原script、10个区域、iframe与9个audio保持。
这是限定已认证输入的准备协议，不能据此声称未知书籍或结构已获支持。

沿用共同AST、Bank规范化、实际复制SHA与读取快照校验，重新准备v3 profile：
`7a870e83fa2c7efb2430269c34c192424fb6d9cd7ec3ca097f70b9b8eda0d67f`，22,459,697字节；
anchors SHA为`c59caed58a41ad3488c8f791ce98c8e386bb40568c5952cda219fef70c0c3c33`。
5,540个实际AST文本节点与修改位置逐一对应，897处改变的受保护exactText精确逆回旧profile；
节点元数据、其它7个字段和其余header依赖不变。e56全正文保护、11处共同宿主适配、64MiB资产限制和10秒完整门均未放宽。
初始编号现在是新编译基线：原作者仍按原序执行，但不声称其私有originals Map／dispose能恢复到编译前的旧数字。
原始来源独立保留。

电脑Safari实际使用同局域网隔离v3页，观察到原完整背面门通过且`compiled_application=compiled-handle-observed`：

| 观察 | 实际时间 |
|---|---:|
| 新页首次完整正面 | 1,951ms |
| 首次请求到完整背面 | 7,642ms |
| 手动返回正面 | 48ms |
| 手动重复完整背面 | 149ms |

两次可选验证均在完整门后运行，只读取公共句柄标量；两次均为`invalid=null`、`disposed=false`，
1,800组、4,303成员、201项Bank，及6,281个Projection wrapper／14个panel符合profile。
它们没有执行全卡DOM扫描，原静态物理次数9,466和主例句5,794不能冒称为本次重新遍历得到的数量。
本结果证明这个真实最大卡输入的完整提交和compiled绑定已通过；**首次7.642秒仍未达到性能目标**。
重复149ms只是一次观察，资源可能已有缓存；父页计时包含消息传递，不是paint、冷缓存或稳定性能上限证明。
尚未据此确认全书、连续导航、手机、音频或Anki客户端的全部验收。

[原始Safari JSON](../output/study-catalog-20261015/compiled-card-largest-numbered-safari-v3.json)为下载原字节，5,235字节，SHA
`74b4e7d50fd2c0f39a359dc63e6bcf025d73cd60e03c546af87bff5bf80bca02`。
[独立compact归档](../output/study-catalog-20261015/compiled-card-largest-numbered-v3/ARCHIVE.md)保留编号准备、v3 profile与QA的小工具、合同、比较、进程证据及原封印；
49MB HTML、22MB profile／fields、5MB计划与1MB逆验载荷只索引完整外部路径／SHA／字节，不复制进Git。
归档步骤仅保存原始结果和更新文档，未重新运行AST／大DOM／浏览器或旧44项合同，未改产品源码、正式入口、PG或APKG。

根线程另在该实际Safari页面展开“足够，恰好”义项，看到20次出现合并为19条原文，筛选2026后为2条；
点击第一条的目标词，实拍可见“took the time／肯花时间”双语chunk共同激活。
[人工UI观察](../output/study-catalog-20261015/compiled-card-largest-numbered-ui-observations-v3.json)与父时钟JSON分开，
不冒称重新遍历全卡、音频／原文跳转全验收或新增可下载截图。

### 最大卡阶段时钟实测与共同加载接缝

新隔离页仍用同一编号HTML746／profile7a87／runtime e56及与v3相同的冻结旧HOST，只在FRAME既有边界增加受限计时。
27处插点逐字逆回`5abf728de9703c405389dccc90a96a939cf7ea76cc83431885189d0f2f7c7133`，
HTML逆回原`1d037…`；原`waitPrepared`／`currentPreparation`／`show`、10秒完整门及接受协议未改变，独立审查已确认。
本次Safari首次完整正面2,370ms，请求完整背面7,775ms，实际观察到compiled句柄，门后检查为`invalid=null`、`disposed=false`，
1,800组／4,303成员／201项Bank保持。完整提交仍通过，首次性能仍不达标；这不是与前一次7,642ms构成的冷缓存或稳定性能对照。

36条受限phase记录给出下列实际边界差值：

| 边界或原作者区间 | 墙钟差值 |
|---|---:|
| prepare-start到原来源proof完成 | 319ms |
| 三资源的并发请求到全部核验完成窗口 | 624ms |
| 资源返回后的额外SHA复核 | 177ms |
| profile JSON解析 | 29ms |
| profile冻结 | 138ms |
| 派生HTML的DOMParser | 760ms |
| 同一9014原作者，第一次／第二次执行 | 457ms／374ms |
| 原9d编号作者，第一次／第二次执行 | 1,713ms／0ms |
| batch-finally刷新 | 738ms |
| 原完整门 | 1,318ms |

资源runtime／profile／HTML各自为53／571／624ms，彼此并发，不能相加代替624ms窗口。
作者区间包含其触发的同步子调用，不能当作独立reader或binder CPU；batch-finally也不能全部归因于编号。
这些是wall／inclusive时间，不是CPU、paint或可相加的独立成本清单。
后续重点是原编号的重复扫描，正在准备严格受限、未知输入拒绝的能力方案；本次诊断没有证明它已提速或可推广。

跨realm比较先对齐epoch：parent请求为`1792187856637 + 109 + 2370 = 1792187859116`，
FRAME准备开始为`1792187857142 + 1976 = 1792187859118`，相差2ms。
它只给出parent请求到prepare-start的边界间隔；HOST内部或完整packet等待没有细分插点，不能为它们分配独立耗时。
完整提交计时仍包含消息传递；既有浏览器缓存、采样差异和绘制完成不由这些记录证明。

[原始下载JSON](../output/study-catalog-20261015/compiled-card-largest-phase-safari-v1.json)保持原字节，19,858字节，SHA
`8eb5d5b7855510ce006c799bf5bb4eb9f3c6a9a47eca7860c35e26b7ad2fc420`。
[独立phase compact归档](../output/study-catalog-20261015/compiled-card-largest-phase-v1/ARCHIVE.md)保留两阶段的小代码、协议、合同日志、manifest及原封印；
`phase-summary.json`从原记录重算差值和epoch公式。既有v3归档、封印及原始报告未改，无大资产复制，未扩大客户端或交互验收。

并行的共同加载工作已修改产品源码`study_catalog_web.py`：提取`verifiedArtifactText`接缝，保留原gzip／hash／abort／budget／fallback，
并在JSON wrapper额外await后复核取消。新增15项合同、64项相关回归通过；定向独立审查的P2修复后通过，根代理另核两例。
这项接缝尚未接入compiled FRAME或发布；本次实际Safari仍执行冻结旧HOST，不能把源码回归当作这次浏览器提速或双端集成完成。
正式入口和PG／APKG保持未变。本次归档任务只新增phase证据与文档，没有执行共同源码改动、浏览器或旧测试。

### 首次编号能力claim v2实际结果与不受控对照

新的严格能力只用于已在生成阶段准备好的第一次编号。实际Safari门后状态为`qualified=true`、`readerCaptured=true`、
`attempted=true`、`accepted=true`、`rows=5794`，reason为`accepted`；读取的是当前文档／token限定的冻结标量状态，未新增全卡DOM扫描。
同一HTML746／profile7a87／e56和冻结HOST保持，原完整门与10秒限制未放宽。
后续canonical刷新、MutationObserver、显式刷新、筛年、增删及dispose算法保留，未知资格回到原刷新。
此资格接受不代表所有书籍／结构均可跳过初始化。

真实Safari首次正面1,835ms，请求到完整背面7,117ms。完整门后compiled句柄`invalid=null`、`disposed=false`，
1,800组／4,303成员／201项Bank符合既有profile。只在这次实际样本中记录下列对照：

| 墙钟区间 | 前次phase页 | claim v2页 |
|---|---:|---:|
| 首次请求到完整背面 | 7,775ms | 7,117ms |
| 原9d第一次执行 | 1,713ms | 42ms |
| 原9d第二次执行 | 0ms | 0ms |
| batch-finally刷新 | 738ms | 1,792ms |
| 原完整门 | 1,318ms | 1,433ms |

这是同一电脑上的两次不受控观察，仍是含子调用的wall时间，不能当作CPU、paint或冷缓存对照。
早期编号段明显缩短，同时后续刷新增长，较多布局工作后移；不能把原1.713秒直接算成整卡节省，
也不能据两次总值声称稳定净提速。首次7.117秒仍未达到秒开目标；正式三书入口未替换，APKG尚未接入。
Cigen布局和gate的下一轮有界分解已开始，尚未完成，不把正在进行的工作写成已修好。

v2还关闭一个独立的引用留存P2：旧v1在首claim接受／拒绝／抛错后仍保留module-private claim函数，
owner disposal仍保留回调。新版本首次尝试的finally清空该引用，dispose清空owner回调。
四个真实闭包cell的确定性契约保留旧非空反例、新null结果及两helper的精确diff；
这证明引用释放，不是GC时序或内存回收实测。旧v1仅保留为历史反例，不能安装旧QA。
原13组行为／状态合同及4-cell日志作为源证据归档，本次归档未重新执行它们。

当前phase FRAME SHA为`bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816`；
27处phase逆回normal FRAME `e40484…`，再按6处claim精确逆回原`5abf728…`，两helper也精确逆回旧v1。
原冻结`1900066a087b48da52b2aea98083aadafa5ad3026e1fc04ca4f5d0a94f3b00ca`和QA manifest
`ba628e917069a7dac2b21581d78c0a4e0f2a64d4cacd12eb6033b6b99a24949b`原字节保持。
[原始下载](../output/study-catalog-20261015/compiled-card-largest-numbering-claim-safari-v2.json)为20,771字节，SHA
`0590ce4b2e2781966521c90e4ea61555848fc6d0d3e65eec07055647f46397ad`。
[独立compact归档](../output/study-catalog-20261015/compiled-card-largest-numbering-claim-v2/ARCHIVE.md)保留helper、证书、builder、反例、合同、原封印和当前frame；
相同SHA的已有基线／协议直接引用，冗余父HTML／frame和大资产只索引外部路径／SHA／字节，不改旧归档。
本次仅新增该证据与两份文档；共同源码snapshot及统一总库计划由其它任务处理，未在这里改写或提交。

### Cigen布局与完整门的真实有界诊断

沿用同一HTML746／profile7a87／e56／claim v2和冻结HOST，只在原Cigen与gate操作周围加入有界计时。
本次真实Safari首次正面1,941ms、完整背面7,197ms，门后compiled句柄`invalid=null`、`disposed=false`，
1,800组／4,303成员／201项Bank保持；初始编号claim仍接受5,794行。独立审查无P1/P2；仅新增隔离QA，正式入口未替换。
这次是诊断结果，不能将7,197ms与前次7,117ms当作受控性能改善或退步；首次秒开仍未完成。

实际冻结快照位于原JSON的`validation_runs[0].layout_cost_status`，范围为body adoption到首次完整门结束：

| 指标 | 次数／实测值 | 包含关系或边界 |
|---|---|---|
| Cigen refresh | 7次，累计2,137ms | wall／inclusive |
| Cigen layout | 7次，累计2,091ms | refresh内的子区间 |
| 每次layout的首个几何读取位置 | 7次，累计2,017ms | 同类读取在batch内也累计2,017ms |
| batch-finally的Cigen刷新 | 1次，2,069ms | 包含上述几何读取，不与它相加 |
| gate检查 | 6次，累计157ms，单次最大49ms | 只计原同步check调用 |
| snapshot | 3次，累计139ms，单次最大49ms | 嵌套在gate检查内 |
| ChildReady短路失败 | 3次 | 只记录原路径实际评价的失败谓词 |

首个几何读取会同步迫使浏览器完成此前累积的样式／排版工作。
2,017ms是该读取边界的wall成本，不能说Cigen自己的JavaScript CPU用了两秒，也不能假设移动读取就消除了成本。
外层phase batch区间为2,070ms，Cigen内部batch计时为2,069ms，边界／计时开销不同，仍不能与内部项累加。
局部selector、computed-style／字体写入、几何读取和原迭代可能互相嵌套；这些记录不是可相加的CPU成本表或paint证明。

`gateFirstCheckAt=8259`、`gateFirstAllReadyAt=8523`、`gateFinishedAt=8664`是FRAME本地`performance.now`时间点，
不是8秒的检查耗时。首次check到首次全部ready相差264ms，之后到完成141ms；首次check到完成405ms。
完整phase gate区间另为1,162ms，不能把检查／snapshot累计值或未插点的等待归成独立可相加成本。
`gateLastBlocker=ChildReady`保留的是最后失败标签，通过后仍保留；不是当前仍受阻。
其它失败计数为0仅限原短路实际评价的谓词，不能推断未评价时字体、原生内容或签名也一定同时ready。
原三次相同snapshot、RAF、来源／token／宽度校验和10秒限制保持，不以诊断放宽接受标准。

七处仪表修改精确逆回claim v2的FRAME `bf909260…`及HTML `d70c033…`；
诊断冻结SHA为`76d165acd3d1e023de6f7e3c083454824878d5e7e1951b346628b3e5e5447f6f`，
QA manifest为`0d8681dc1068dc23dcaf7ef70e30ba7b38cd7bdec646d4b0340938f1803c71c3`。
13项小合同的原操作／查询／样式／消息／异常／RAF轨迹证据及原封印保留，本轮归档未重跑合同或浏览器。
[原始Safari JSON](../output/study-catalog-20261015/compiled-card-largest-layout-cost-safari-v1.json)保持22,769字节，SHA
`e16414a795739c8ee132ba23499787edf317c07a4244b6a41119e502443a2ff9`。
[独立layout compact归档](../output/study-catalog-20261015/compiled-card-largest-layout-cost-v1/ARCHIVE.md)复用既有同SHA基线，
仅保存新小代码／协议／合同／manifest和当前FRAME，冗余HTML／config及大资产只记录外部路径／SHA／字节。
本次只改README、本计划与新增证据，未动UNIFIED计划、产品源码、旧封印、PG或APKG，未运行大DOM或producer；下一步优化尚未完成。

### 当前成功资源任务的校验证明复用

沿用同一HTML746／profile7a87／e56／claim v2与layout诊断接线，只在原资源获取路径增加三处编辑。
原资源任务仍先完成HTTP、范围、UTF-8及SHA校验；私有WeakMap只记录该当前成功任务的原始字符串与pin。
调用点须同时匹配当前reader、URL、pin和primitive字符串，且证明严格返回`true`，才能复用该成功结果。
伪reader、pending、已淘汰／替换任务、不匹配、失败或证明登记失败均保留原`matches`回退；原24任务缓存、异常身份、当前owner与取消行为不变。
这不是跳过来源校验，也没有把可伪造的调用方布尔值作为证明。

相同三资源的真实函数小合同记录原路径6次`matches`、候选3次；源阶段9项定向合同通过，包含伪reader／错pin、范围失败重试、缓存淘汰、异常身份、取消和登记失败回退。
这里的6→3是校验调用次数，不是六项测试。原RED／GREEN与精确编辑／逆验已归档，本次未重跑合同、浏览器或大DOM。

真实Safari首次正面3,203ms、首次完整背面11,808ms，原完整门通过；门后compiled句柄`invalid=null`、`disposed=false`，
1,800组／4,303成员／201项Bank保持，初始编号claim仍接受5,794行。
`compiled-assets-verified=3842`与`compiled-recheck-verified=3842`相同，额外复核边界为0ms；上一layout原始记录的对应差值为142ms。
这支持记录精度内的重复复核已消除，不能把0ms解释为原首次SHA验证也被取消。

| 指标 | 上一layout样本 | 本次resource-proof样本 | 比较范围 |
|---|---:|---:|---|
| 首次完整背面 | 7,197ms | 11,808ms | 同台不受控完整提交样本 |
| 额外资源复核边界 | 142ms | 0ms | 三资源已首次验证之后 |
| 首个几何读取累计 | 2,017ms／7次 | 3,508ms／6次 | 可能同步完成此前累积的排版 |
| batch-finally的Cigen刷新 | 2,069ms | 3,676ms | 包含几何读取，不与上项相加 |
| 来源proof区间 | 223ms | 576ms | 墙钟差值 |
| DOMParser区间 | 759ms | 1,070ms | 墙钟差值 |

其它阶段也增长。各区间含子调用，不能相加或当作独立CPU成本；不能从这两个不受控样本宣称整体提速，也不能归因候选导致回退。
根代理同刻观察到约28% memory-free、WindowServer约84% CPU、fseventsd约77% CPU；这些不是本归档采集的系统样本，
只支持环境并非空闲，尚不能确定性能变化根因。仍无冷缓存、paint、稳定延迟或首次秒开的证明。
原10秒完整门只约束其自身阶段，不能把11,808ms总背面时间解读为放宽了该门；所有原接受条件保持。

候选冻结SHA为`c247b83ff98a7932afbb6633ff593c42bfef90ffa3df3a8fe512abecc6470f5a`，
QA manifest为`4ed43f7d68b22cf701272aa3020b19bd1c1e359d2b4c900adc5c8d3097a79fca`。
[原始Safari JSON](../output/study-catalog-20261015/compiled-card-largest-resource-proof-safari-v1.json)保留22,898字节，SHA
`3f2aafcc10150249ed96b8f6f49c77149abd82150ca42dbaa76013069b50e0d6`。
[独立compact归档](../output/study-catalog-20261015/compiled-card-largest-resource-proof-v1/ARCHIVE.md)只复制三处编辑、新helper／合同／工具／封印及原始记录，
复用上轮不可变基线；可从基线与编辑重建FRAME并精确逆回原SHA，不重复复制完整FRAME、父HTML、config或大资产。
本轮只新增该raw／归档并更新README和本计划，保留先前封印和README的学习模块／分类状态说明。
根代理仅安装一个隔离QA，三个正式入口未推广，APKG共同生成层未接入，性能目标尚未完成；产品源码与UNIFIED／PG未由本任务修改。
