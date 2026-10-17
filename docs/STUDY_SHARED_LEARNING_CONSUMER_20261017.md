# 学习页复用共同卡片宿主

正式PG学习迁移及34表恢复已经完成。本阶段保持同一库、同一学习业务和旧book/card/deck身份，
把学习页的显示适配接到三个浏览入口已经使用的HOST／FRAME，不另造字段渲染器。
源码、隔离检查、实际浏览器、正式部署和Anki接受范围分别记录；此计划不是已完成声明。

## 本阶段实现

1. 在现有共同HOST中提供显式嵌入消费模式，复用原fetchCard、front/full来源绑定、缓存、取消和FRAME。
   普通目录模式和旧目录布局保持；嵌入模式隐藏目录控件，由外层学习页负责评分和范围。
2. 暴露`StudyBookEmbed`能力接口：配置门前偏好与键盘回调、选卡、请求正反面、偏好刷新、当前提交状态和销毁。
   评分只接受当前generation、当前card、当前实际文档在原完整门之后提交的背面，不能用attachComplete的接受回执替代。
   门前应用字体／隐藏区块／音源等偏好；偏好变化重新确认完整就绪，空格和1–4等一次按键只执行一次。
3. 服务提供只读交付描述，明确旧学习身份到canonical card ID、正式入口和wrapper的关系。
   两张guide沿已批准native/GUID转换，四张补充卡不隐式新增旧学习行；数据来自已认证v2路由。
4. 将学习页JS／偏好适配纳入版本化共同资源，保留原评分、撤销、请求幂等和控件功能。
   音频配对复用原始共同wrapper payload解析器及每面真实base，不执行脚本、不跨音频组配对，不改录音字节。
5. 同书、同正式entry只配置一个HOST／controller，逐卡调用既有`select()`；不能每次评分后销毁整本HOST，
   再重复读取目录、解析索引和创建模块缓存。每次选择仍有独立、不可原地改写的旧评分身份和新selection代次。
   固定宿主导航身份与逐卡canonical身份分开验证；换书、真实导航、失败／重试及退出页面仍完整销毁。
   保留既有4卡／16MiB和24脚本等缓存限额，不无限保存背面。

## 验收顺序

先做小型真实HTML／DOM合同、取消／ABA／偏好／键盘／错误反例和独立diff审查，再用私有学习快照及隔离服务做Safari实测。
三本书均检查实际正反面、年份／例句、偏好、键盘与音频，保留当前正式服务和原资料。
正常展开义项／审核或词源例句后，直接评分也须有效。`ready`表示当前实际Document已通过原完整门并提交的事实，
要求私有commit记录、当前packet／view token／consumer代次、真实connected Document及非working状态全部相符；
合法展开／resize本身不撤销该事实，也不在每个按键重复扫描整页几何。每次显示／翻面／显式偏好刷新仍经过原门，
切卡、取消、换consumer、销毁及终态错误立即撤销资格。评分按钮、数字键与`spaceAction=good`覆盖取消／重复操作负例。
通过后才原子更新小型HOST／FRAME及学习资源并验证正式入口，不重建15,174份无变化卡片或重复迁库。
最大卡速度及compiled共同Anki生成仍是独立未完成项，不因新消费者能显示内容而勾选完成。

该阶段不授权远端操作，也不写真实Anki集合；关键节点继续本地Git。

## 当前证据与未完成范围

`0976f19`已保存共同wrapper音频解析及模板惰性内容边界修复，原录音、旧明文路径和响度算法保留。
只读delivery接口、共同HOST／FRAME消费能力和学习客户端已实现；截至评分恢复补充修复前，
112项相关回归完成，其中1项可选PG检查跳过、其余通过，独立审查发现的快捷键及视口翻面问题已修。
隔离Safari已观察2027说明卡／radiate、2026 remote和刘晓艳ambition的完整内容；
remote原文、语境释义及完整旧审核可展开，英美录音出现正在播放状态，私有学习副本未产生评分。
该观察随后又复现“展开词源例句后直接评分无响应”，因此不将当时版本列为可切换。
随后两处ready事实语义修复与临时workaround撤回已独立复核。最终实际HOST／FRAME小组合覆盖
直接按钮、summary焦点数字键、SpaceGood与EnterGood，原15个业务／键盘函数逐字保留；
3项历史整FRAME封印先逆回明确的2处ready变化及9处消费增量，再执行原SHA与原算法断言，未改旧预期。
159个包成员在离线干净wheel及仓库外安装后逐字核对，安装后导入未连接PG。
最终新源码Safari隔离副本已检查三书代表卡，实际重做ambition→展开exit例句→良好只保存一次并进入action，
键盘Z撤销后回到ambition／今日0次；remote原文／完整旧审核可展开，实际字体18→20偏好保存和刷新成功。
写入仅发生在私有SQLite副本；正式PG进度、原SQLite、真实Anki和正式入口没有改动。
[本阶段实际UI范围](../output/study-catalog-20261015/shared-learning-consumer-v1/functional-native-observations.json)、
[源码封印](../output/study-catalog-20261015/shared-learning-consumer-v1/functional-current-pins.json)和
[安装验证](../output/study-catalog-20261015/shared-learning-consumer-v1/installed-package.json)分别保留。
随后同书缓存生命周期复用已通过源码、小组合及隔离Safari验收，详见下节；正式切换继续验收，
最大卡首次秒开和共同compiled Anki生成也未完成。

## 同书宿主复用的实际验收

学习客户端`60d63bf53433f673039d10cac5a9bc798f2538afdfc2985bdaccc44f305baab4`保留同书同entry的
一个HOST和controller，仅调用原`select()`。每张卡的新immutable selection、serial、最低generation和真实文档
共同决定当前评分资格；评分业务仍取当前后端revision，标记／笔记更新不冒充换卡。
独立审查发现的旧文档键盘误路由及首选择强引用均先复现再修复：事件只接受当前已提交面或固定HOST文档；
退休选择释放文档／controller／WeakMap等引用，长期load/error处理器只持有HOST。
原15个业务／键盘函数逐字保持，HOST／FRAME／偏好本轮未改，现有缓存限额保持。

6项unittest包含41项小用例及5组真实完整HOST／FRAME组合；A→B→A仅配置、导航读取、索引读取和FRAME初始化各一次，
旧卡、旧面、无关文档携带当前snapshot也不能评分。独立复跑5项针对性反例后，无剩余P1／P2。
干净离线wheel及仓库外安装核对159个包成员，安装后导入未连接PG。

实际Safari私有副本中，ambition展开exit例句后“良好”一次进入action，action主文档数字3评分后进入activate，
Z撤销回action、今日2次降为1次。保存action笔记后仍能显示完整背面和评分入口。
同一页面随后切换2026、2027红宝书，两张GUID说明卡的原正反面均可见。
请求日志表明三书各只读取一次HOST入口、目录和prepared索引；刘晓艳的连续评分和撤销未重读这些资源。
实际嵌套词源iframe内数字键未评分，原学习页也只对主卡片文档绑定键盘；不把此项列为已新增支持。

[完整小组合及反例](../output/study-catalog-20261015/shared-learning-host-reuse-v1/REPORT.json)、
[实际UI和请求范围](../output/study-catalog-20261015/shared-learning-host-reuse-v1/native-observations.json)与
[安装结果](../output/study-catalog-20261015/shared-learning-host-reuse-v1/installed-package.json)分别保留。
写入仅在私有SQLite副本发生，正式PG、原SQLite、真实Anki和正式入口未改；自建服务和Safari窗口已关闭。
本次没有冷缓存／绘制完成／数字速度或最大卡秒开结论。下一步是同PG正式presentation切换及入口验收。

## 正式接线及原入口验收

上述后续接线现已完成：现用PID64404读取同一PG及认证v2注册，原双回环端口和LAN代理40631保持。
三书只更新小型HOST资产、index、COMPLETE及原label的plist；cards／media／catalog／evidence原件复用。
正式学习页沿同一共同能力消费完整正文，原学习book／card／deck身份、评分及撤销规则保持。

首次操作器只对loopback正确核原文件SHA，却对LAN代理已经插入两条SRI脚本的HTML作相同假设，
正向及自动回退的最终HTTP门均误报失败。旧失败记录不改写；事后逐项证明原10文件及旧展示已恢复，
回退前后学习10表全部行摘要一致。独立审查后仅修精确LAN预期计算，拒绝未知脚本／缺失注入及单字节漂移，
保留loopback原字节门；重新封存实际writer61710及原件后再次执行，全部接线门通过。
没有改动LAN代理，也没有回灌SQLite、迁库或恢复旧学习行。

第二次切换前后及Safari实际验收后，15,177条typed rows摘要均为
`ea443b2471f029b0141bbee48558b75c5035f778c19c7dc600466edb7a848152`。
实际LAN Safari通过2027 radiate、2026 remote、刘晓艳ambition的完整正反面；
remote的原句／完整旧审核／完整记录可展开，英美录音控件各出现正在播放状态；
ambition展开exit例句后反复翻面仍保留该例句。正常目录保留原三栏布局，radiate点击到radiant再翻背面可用。
本次未在正式库评分或编辑；自建Safari窗口已关闭。没有冷缓存、绘制完成、真实手机或最大卡速度结论。

[失败检查及实际恢复状态](../output/study-catalog-20261015/shared-learning-presentation-v1/attempt-1-failed-check-restored-state.json)、
[正式结果](../output/study-catalog-20261015/shared-learning-presentation-v1/result.json)、
[实际UI范围](../output/study-catalog-20261015/shared-learning-presentation-v1/native-observations.json)和
[源文件封印](../output/study-catalog-20261015/shared-learning-presentation-v1/source-pins.json)分别记录。
共同学习前端接线已完成；最大卡首次速度与共同compiled Anki产物继续执行原计划。
