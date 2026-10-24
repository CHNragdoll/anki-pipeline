# 网页学习状态迁入PostgreSQL：当前实际进度

截至2026-10-18，本地开发分支`feat/unified-study-database-20261015`的**内容主库和现用网页学习状态已统一到PostgreSQL**。
正式停写、最终快照、导入／分类同事务、逐行对账与双回环单writer切换已实际完成；现用库34表、总库revision 14。
新版wrapper的共同学习前端、同书宿主复用及三书全量共同渲染已接入原入口；两年完整原生候选已通过归档与默认更新，但最大卡秒开、包体积和浏览预览尚未通过，
本页不代表远端合并、发行或真实Anki集合修改。

## 正式学习迁移与当前运行服务

切换前先将真实主库全部24表再次与已独立恢复的原生备份核对，全binary COPY流一致，约67.89秒。
停止原launchd writer后重新封存最终SQLite，SHA
`2bafb58181ddb141052750041a888e326a3b272c03c89caebb5350b08ed7efa5`，2,213,005字节。
READ COMMITTED事务中按learning→catalog顺序持锁，建10张专用学习表，导入完整快照并登记三书英语／考研分类，
提交前及提交后逐行／类型／JSON原文／空值／sequence缺行对账均相等，合计15,177条typed rows、15,170张卡。

首次迁移时，原label下新PG服务PID 44323独占127.0.0.1／::1的8771；原LAN代理PID 40631保持。
停服至本机双回环和192.168.3.5接口恢复共12.59秒。三个overview响应字节相等，书架和三书正式浏览页均200。
Safari自建窗口实际检查2027说明卡及radiate、2026 remote、刘晓艳ambition的原学习正反面；
例句／词源可见，未提交评分，检查后全部学习typed rows仍与最终快照相等。自建窗口已关闭，用户原窗口保留。

[正式结果](../output/study-catalog-20261015/learning-cutover-v1/result.json)、
[输入封印](../output/study-catalog-20261015/learning-cutover-v1/inputs.json)、
[同事务对账](../output/study-catalog-20261015/learning-cutover-v1/migration-reconciliation.json)及
[原生UI人工观察范围](../output/study-catalog-20261015/learning-cutover-v1/native-ui-observation.json)分别保留实际证明。
原SQLite和私有最终快照均未被替换；原始学习行不进Git。失败回退操作先停止PG writer，再把最新PG状态导出到新SQLite，
不会启动落后的旧副本；该分支有隔离合同和本次操作配方独立复核，本次切换成功，未执行真实回退。

随后`b61fbf6`及`aa32cbb`实现共同学习消费者及同书宿主复用，原15个业务／键盘函数逐字保留。
现用服务PID 64404使用正式v2注册，不再带`--allow-legacy-catalog`；双回环8771仍独占，原LAN代理40631未改。
学习页和全书目录使用同一HOST／FRAME、完整准备门、认证来源和有界缓存，不再逐卡销毁整本宿主。
共同wrapper音频解析已保存为`0976f19`，原录音字节及旧明文能力保持。
第一次接线的LAN检查误把代理固定增加269字节的响应与原文件直接比较，自动回到旧展示；
旧失败receipt保持，独立核对原10文件恢复及三份学习证明相同，没有导回或覆盖学习记录。
检查器改按冻结代理的精确变换核验后重新封存当前writer和原件，再次接线通过。
切换前后及正式Safari检查后，全部10张学习表的15,177条typed rows摘要均为`ea443b24…a848152`。
Safari实际检查三书学习正反面、remote来源／完整旧审核和英美播放状态、ambition展开例句后重复翻面，
以及原三栏全书目录的radiate→radiant切卡和完整背面；正式服务未评分或编辑。
评分／撤销／笔记的正例在独立私有进度副本验收；[接线计划和详细范围](STUDY_SHARED_LEARNING_CONSUMER_20261017.md)、
[正式接线结果](../output/study-catalog-20261015/shared-learning-presentation-v1/result.json)与
[实际UI范围](../output/study-catalog-20261015/shared-learning-presentation-v1/native-observations.json)分别保留。
前端共同接线已完成；最大卡速度、真实手机及共同compiled Anki生成没有由这些证据自动完成。
切换后34表原生备份封存7,001,407,762字节，全部8,134,185行在独立Unix-only实例中恢复，
全部列及完整binary COPY流一致；其中15,177条为专用学习状态。备份194.25秒，恢复及核对287.94秒，
含停止验证实例共483.72秒，实例exit 0、已确认停止。外部manifest SHA为
`9167fceb7d733b2536449ec5b6aad59817c91d88754bbf47c95c4f0cbc87d9f7`。
[34表完整证明](../output/study-catalog-20261015/native-learning-recovery-v1/verification.json)、
[实际阶段结果](../output/study-catalog-20261015/native-learning-recovery-v1/result.json)及
[本阶段完成范围](../output/study-catalog-20261015/learning-cutover-v1/completion.json)相互绑定。
初始切换result中“34表恢复待验”的字段保留其写入时状态，由后续completion补足，不改写原始结果。

## 已完成的能力与证据

指定三书内容、旧词库及完整审核历史早已进入同一PG内容库，共3本书、15,174条笔记、3,029,869行历史原始记录。
共同Anki／网页导出和原包对账已完成；旧格式内容库备份曾恢复到新schema，24表、8,118,998行完整payload独立对账通过。
这部分不需要为了迁移网页学习记录重新执行，详见[内容库验收](STUDY_CATALOG_ACCEPTANCE_20261015.md)。

网页学习迁移所需的公共实现已经提交为以下本地节点。测试数量是根代理已记录的各自验收范围，彼此有重叠，不能相加为独立总数；本次文档整理未重跑。

| 能力 | 已提交节点与验证 | 证明范围 |
|---|---|---|
| 原样保留共同学习业务 | `7230425`：提取时与旧实现56,861字节完全相等，原64项业务／HTTP／快照合同通过 | FSRS、队列、日界、评分、撤销、设置等沿用原业务，并非重写另一份PG调度器 |
| 同一业务连接PG存储 | `7ea4026`：25个原方法AST相同，仅6个存储接点变化；最终91项通过，含原64项、PG 19项及分类8项 | 隔离PG内的响应、事务与状态对照；不证明现用服务已切换 |
| 版本化完整备份和恢复 | `8e5acfc`：兼容旧24表v1，新v2覆盖完整34表及恢复对账；42项相关测试通过，独立复核的P2已关闭 | 新格式和恢复能力已实现；不等于新版正式全库备份／恢复已跑完 |
| 同一私有快照与外部SHA封印 | `094a0aa`：41项通过，含25项snapshot与16项seal合同 | 后续读取同一已封存快照，外部SHA保护不被副本替换；不是自动导入或自动切换 |

整表迁移器已完成隔离验收：23项专用合同及83项必要相关回归通过。迁移计划与导入要求调用者开启
READ COMMITTED事务并先持学习锁，函数再取得共同目录锁，两个锁保持到外层事务结束；旧RR／SERIALIZABLE
快照明确拒绝，不能在等待锁后继续依赖过时身份。发布alias和receipt后再次逐行核对全部十张学习表及两条发布原文，
并发改动、发布触发器侧写、失败或取消都不能被报告为成功。只读对账仍支持RR／SERIALIZABLE。
这证明迁移代码在隔离库中的行为，不代表正式学习库已导入或切换。

## 正式全库备份、独立恢复及实际学习数据排演

`9d31f69`的PG17原生备份已在真实总库执行：封存24表、8,118,998行，归档7,000,034,353字节。
原生导出121.93秒，同一来源快照的完整binary COPY证明53.40秒；含封存和复读的总备份时间205.71秒。
独立Unix-only私有实例的恢复及全流核对347.46秒完成，全部列和全部行一致，实例已正常停止。
首次临时实例因Darwin套接字路径131字节超过103字节限制而启动失败；改短路径后直接复用同一外部pin归档，未重新导出。
这些是本次实际耗时，不是其他机器或后续数据库规模的上限。

在已核验的完整恢复副本中，实际观察学习快照也完成了迁移、三书分类登记和导回SQLite：
15,170张卡、合计15,177条typed rows前后一致，原始JSON、类型、空值及sequence缺行保留。
实际排演约6.63秒；`ca5067f`的导回能力也覆盖切换后新写入状态的隔离合同。
上述排演结束时正式库仍为24表、revision 11；它不冒充正式切换。后续正式操作及当前34表状态另见本页开头。

[完整原生恢复证明](../output/study-catalog-20261015/native-full-recovery-v1/native-verification.json)及
[实际阶段与排演摘要](../output/study-catalog-20261015/native-full-recovery-v1/result.json)记录外部pin、全表证明和边界。
原始备份、实际学习行和SQLite文件保留在私有目录，不进入Git。

目录provider随后也在该实际恢复副本的只读RR事务中装载成功：旧三书1,960／6,680／6,530张卡，
返回的完整books JSON与现用旧load_books输出字节相等。provider与共同PG StudyStore构造前后的学习typed rows不变，
没有初始化或补卡。[实际PG装载记录](../output/study-catalog-20261015/native-full-recovery-v1/provider-actual-result.json)
保留当前源码和注册配置摘要；记录中的5.46秒包含全状态前后读取，不是每次翻卡耗时。专用只读实例再次正常停止。
此项仍不证明正式HTTP服务或原网页入口已切换。

共同HTTP／音频及双回环启动器随后在同一完整恢复副本上完成真实整服务检查：18项API／静态检查通过，
三书15,170张卡的API返回与旧SQLite业务一致，全部学习typed rows前后不变，关闭时确认请求排空。
[初次默认整服务记录](../output/study-catalog-20261015/native-full-recovery-v1/default-service-actual-result.json)之后，
新增的显式v1兼容启动也在真实恢复副本重验，
[当前兼容路径记录](../output/study-catalog-20261015/native-full-recovery-v1/compatibility-service-actual-result.json)约6.23秒完成。
其中只有业务时钟固定用于字节对比，数据库、provider、Store、HTTP／音频均走实际公共实现；不是现用服务已切换的证据。

v2注册现可把旧卡片URL精确委托正式PG导出wrapper和媒体，旧catalog及学习身份不变，未知路径和别名拒绝回落旧文件。
但旧学习界面的`preview-flip/front/back`和明文音频提取器尚不兼容新wrapper，v2路由目前仅为候选。
正式学习迁移先使用私有v1注册及明确的`--allow-legacy-catalog`保持现有展示，不能把路由HTTP 200视为刷卡验收。

实现见[共同学习业务](../anki_pipeline/study_progress.py)、[PG存储](../anki_pipeline/study_progress_pg.py)、
[快照读取](../anki_pipeline/study_progress_snapshot.py)、[迁移封存](../anki_pipeline/study_progress_migration.py)和
[备份恢复对账](../anki_pipeline/study_catalog_recovery.py)。原业务规则只保留一份，存储实现不能另改评分或学习语义。

## 真实身份核对与当前学习库观测

[只读身份报告](../output/study-catalog-20261015/learning-bindings-audit-v1/README.md)已生成并通过独立复核。
完整身份文件[learning-identities-readonly-20261017.json.gz](../output/study-catalog-20261015/learning-identities-readonly-20261017.json.gz)
为929,649字节，SHA `986735ddee5a64b16c3cab5fbaf938b3a151a15473fab0581267e11305d99592`。
其作用是固定旧目录到总库的身份关系，不含现用私有学习快照；正式迁移仍须复核目录SHA、目标tuple和学习快照。

| 旧网页命名空间 | 旧学习目录卡数 | 总库native卡数 | 差额解释 |
|---|---:|---:|---|
| `liu` | 1,960 | 1,960 | 保留旧namespace，不按单词拼写猜身份 |
| `redbook` | 6,680 | 6,682 | `teem`、`deep-rooted`两张总库补充卡不在旧学习目录 |
| `redbook2027` | 6,530 | 6,532 | 同上，两张补充卡仍保留在内容主库 |
| 合计 | 15,170 | 15,174 | 四张差额有明确身份，不隐式新增学习行 |

全部15,170个旧`(book, card_id, deck_id)`都有精确的目标书、source、note／GUID／model、native card、template与unit tuple。
两张说明卡还各有显式证据：2026沿原builder身份公式与实际native tuple绑定；2027沿原修正版APKG身份及旧页面完整字段绑定。
旧guide ID与新导出GUID不同已记录为关系，不当作缺失，也不改成按英文词头合并。
[摘要结果](../output/study-catalog-20261015/learning-bindings-audit-v1/result.json)明确为`ready_to_switch=false`；身份核对本身没有读取学习记录、写PG或切服务。

根代理另对现用网页学习库做了只读封存观测：cards为15,170行，metadata为1行，settings为3行，undo为3行，
其余业务表当时为0，revision为15,170；没有对源学习库写入。
这是该时点的真实观测，不能沿用为最终切换快照，也不能推断用户以后不会产生新评分或设置。
私有AppSupport快照不加入Git、不提供公开下载；实际切换前需重新取得一致快照并验证期间变化。

## 尚未完成的交付

1. **网页首次长卡速度与共同产物接线。** 最大卡此前隔离Safari完整背面7.419秒；后续同源A→gzip B→A对照为4.464／8.959／6.575秒，未证明压缩候选净收益，仍未秒开。按用户确认，A完整路径已[接回三本原入口](STUDY_COMPLETE_RENDER_ADOPTION_20261017.md)，随后三书全部15,174条笔记已生成，其中13,212张红宝书词卡采用共同渲染；两年完整原生候选也已生成并完成默认后端导入核对，原发行附件尚未更新。重复149ms及某处SHA复核142→0ms不能替代首次完整背面目标，详见[编译方案与实测边界](STUDY_COMPILED_PANEL_PLAN_20261017.md)。
2. **新compiled产物的最终客户端与交付。** [v2完整包](../output/study-catalog-20261015/complete-anki-redbooks-v2/README.md)已完成真实源／候选归档核对和两年默认更新、重复导入及完整媒体／学习状态验证。正常刷卡的abide两处原句完整，但实际浏览预览暴露编辑器删除script末尾的问题，正在做纯文本末尾的两卡修复验证；900.8／821.7 MB的包体积也未达标，真实手机及最大卡仍未验收。

完成标准是：正式登记、当前学习数据无损导入／对账、新版完整备份／恢复、单writer切换／回退和实际客户端操作分别有证据；
网页速度与Anki共同生成也须单独验收。现有内容总库完成状态、五张网页实拍和原Release下载继续保留，不能把这些待交付项写成已完成。
