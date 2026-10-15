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
