# 生成阶段语义处理与显式新交互绑定

这是统一总库／共享生成工作的性能后续，不另建数据库，不缩小为只让小卡可用。
分支为`feat/unified-study-database-20261015`；基线共同源码SHA为`caf263d17768d63a0f3fc01813f8204b8b44b23f63414b6ab69f273692177b3d`，
FRAME为`c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02`。
正式三个入口保持此前206版本。前置迁移／恢复证据继续有效，本计划初阶段不写PG、APKG、媒体或真实Anki集合。
实现已由用户授权；此计划不授权远端推送、PR、合并、发行。

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
