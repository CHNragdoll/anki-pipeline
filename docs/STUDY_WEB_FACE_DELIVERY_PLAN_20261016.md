# 独立正面交付与完整背面预备

目标：点卡先完整显示正面，不再等十几MB背面资料全部读入；背面保持原严格校验、完整准备后一次显示。当前共同host v10已加入精确类别扫描和独立脚本资源并发；最长卡首次翻面仍以秒计，目标未完成。

## 已确认原因

more原wrapper约16MB、prepared JSON约19MB，当前fetchCard等两者到齐才mount正面，而正面只有2,801 UTF-8字节。不要用缩减内容、删历史、宽松校验或逐段可见加载解决。

## 最小实现

1. `prepare_library`在同一次完整wrapper编译核验内，额外写小front artifact，包含原sides[0]精确字符串、prepared侧0及proof、相对base元数据、同一modules cohort。新prepared index的card项封存front文件SHA和card/source wrapper/payload/front哈希绑定。保持原始导出、整卡prepared和缺少front项的旧路径。
2. `HOST_RUNTIME`先核验现有config根pin下的新index，再核小front artifact的SHA和完整绑定；动态按当前wrapper URL解析相对base。正面提交后，后台继续原fetchCard/readAuthoredCard/preparedCard严格下载、骨架/双面/base/完整wrapper和sideproof核验。不得凭编译证书省掉背面的原始来源校验。
3. `PREPARED_FRAME_RUNTIME`新增显式front-only会话和完整包attachment。front-only不可填假背面/空proof；现有prepareView(0)及native/脚本/子文档/字体/完整布局门槛照旧。整包核验后只attach到同一current/token，不重新mount重建正面；然后后台getView(1)。翻面期间仍保持完整正面，到背面真正ready才promote。

## 必须守住

- index中新增小front字节SHA；大artifact SHA本身不认证未下载切片。来源绑定包含同card、同index快照、同wrapper/payload/front SHA、同base与modules。
- generation/token贯穿每个await，A→B→A旧任务/失败都不能复活；导航及时取消。当前整卡必要准备不受邻卡2MiB投机预算误伤。
- 小front/整包共用现有4卡/16MiB保守LRU；超大整包仍不缓存，无新增无界缓存。只有当前card的2个真实connected面。
- 任何front缺pin、bytes/hash/来源不同，或整包与已展示front不一致，均只在仍为当前token时走原wrapper fallback。过期结果不改当前UI。
- `.sf-ownership-history`含as-manifest必须原样初始化discover。此前history template/字体hold/CSS containment诊断候选均未推广，不混入本次实现。
- APKG、PostgreSQL、学习记录、源卡、原音频、例句/chunk/审核历史和物理计数不变；三本当前书与未来factory走同一实现。

## 验收与节点

先失败回归，再实现：新front错SHA/错card/错快照/base/modules、完整包不一致、取消及A→B→A、back未就绪不闪半面、源脚本原序、legacy无front回退、共用缓存预算。导出前后整卡文件/计数与既有prepared内容逐SHA核对。

先对独立QA导出验证普通卡和more，记录首次正面/立即背面/读正面后翻面、连续切卡及几何稳定性；626主例句、688物理次数、578历史引用必须保留。失败不覆盖正式入口。通过后CAS推广三入口，记录回滚、本地Git、更新安装验收。网站实测不能替代手机Anki验收；不发布远端或Release。

## 10月16日实现及隔离验证

生成器已为每张卡输出独立、带来源绑定的小正面；host先验证小正面，后台继续验证原完整wrapper与整卡artifact。frame用同一会话原位接入完整双面，不重建已显示的正面。立即翻面会等真实背面就绪，快速切词会取消旧会话。完整artifact字节和既有4卡/16MiB缓存、2MiB邻卡预取上限保留。

失败重现使用HEAD的原host并拦住完整wrapper：原host不能先显示完整正面，新host通过。相关测试执行69项：59通过，10项因未指定隔离PostgreSQL连接而跳过（本次不改数据库）；独立复核host26合同、frame13种错配/取消/ABA、生成器及混合缓存预算通过，无P1/P2。v13干净安装133文件逐SHA一致，两个CLI和MathJax资源通过。

真实局域网QA中，more从相邻卡切入正面57.8ms，读正面后完整翻背面27.8ms；普通objective切入143ms，预备后的翻面6.2ms。more的626主例句、688物理次数、578审核历史、native ready均保留。整页首开more正面实测651.9–1332.5ms，首次立即请求背面仍3297.8ms；后台预备使后续翻面迅速，不代表首次立即翻长卡已全部秒开。不同轮次主机负载/cache会影响结果。

原始计时及内容证据在`output/study-catalog-20261015/independent-front-{auto,normal,within-book}-actual-ui-v1.json`。

全量15,174张卡已补齐front artifact，原wrapper/payload指纹与旧报告逐书一致、fallback为0。三书原入口已推广为`study-web-host.v11-independent-fronts`；备份、来源封印、计划和条件回滚位于`host-upgrades/independent-front-v1`。准备阶段仅结束日志函数重名报错，全部数据及封印已完成；修复后保留旧日志/脚本/plan并重封，未重跑或覆盖front，随后promote退出0。详细记录见阶段验收6.7。

三正式入口实点翻面通过：2027 radical 9例、2026 remote 4例、刘晓艳 ambition 23例；正式more复核626主例句、688次数、578历史及native ready。完整背面仍一次显示，原目录和链接保留。最大卡首次立即翻背面的约3.3秒限制仍存在，不把这轮推广等同全部首次秒开。

## 后续原页传输优化

v11之后已增加公共原wrapper无损gzip，三书15,174张原页由1,974,259,756字节对应339,043,363字节副本；原source/full/front/prepared index和FRAME就绪门槛不变。已推广为v12，原三个入口实际完整翻面通过。该变化只确认传输缩小和内容完整，首次长卡仍有数秒及更高负载波动；3.3秒是前一轮观测，不是固定上限。完整来源、验证、恢复与Safari验收边界见[本轮记录](STUDY_SOURCE_WRAPPER_GZIP_20261016.md)。
