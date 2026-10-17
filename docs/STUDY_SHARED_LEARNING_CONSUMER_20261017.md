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
同书缓存生命周期复用及正式切换继续验收；最大卡首次秒开和共同compiled Anki生成也未完成。
