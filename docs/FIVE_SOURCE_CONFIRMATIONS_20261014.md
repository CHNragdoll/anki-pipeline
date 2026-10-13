# 五处来源核验与校勘（2026-10-14）

本次为用户授权的本地数据修复（bug / R2），交付目标是当前网页卡片、重排版及整卷版同步。保留原始 PDF、原版网页、历史快照、原句与旧审查说明。使用受范围约束的派生文本校勘及增量快照，不修改原始资料，不改变学习进度、卡片身份或已发布 APKG。

## 已核实的五处

| 位置 | 本次处理 | 证据与界限 |
| --- | --- | --- |
| 2017 英语二 Part B，41–45 题说明，`number items` | 派生文本校正为 `numbered items`；归入 number「给……编号」的过去分词修饰用法 | 用户已核对其他版本并确认漏 `ed`。保留旧字样及校勘记录；同步后续字符偏移、chunk 与来源跳转。 |
| 2001 统一卷阅读 Text 5，第 3 段，`jugging your life` | 派生文本校正为 `juggling your life`；归入 juggle「同时应付／兼顾」 | 用户已确认 `juggling`；同篇后文及第 39 题亦有正确拼写。错误 jug 归属迁至正确词条，保留完整转归依据，同一位置只计一次。 |
| 2015 英语一完形，第 5 段，`picked pace` | 保留来源字样，说明语境为「加速」及通常搭配 `pick up pace` | 对应 IBTimes 报道（2014-07-15）原样写 `picked pace`。不能继续标为本地解析漏词，也不能把「加速」冒充普通 pick 的词典原义。 |
| 2025 英语一阅读 Text 2，`remote heat` | 保留来源字样，说明实际指回收后用于区域供暖的热量 | FT 对应文章（2024-01-03）原样如此；LUMI 官方确认回收设备余热供暖。整句中文「余热」不能反推 remote 独立词义。 |
| 2026 英语一完形第 6 空后，`as convenient and provocative` | 保留来源字样与句意说明，替换「疑似 PDF 漏词」判断 | Psychology Today 对应文章（2023-06-19）原样如此。原文字样已核实；as 的具体语法关系及唯一词典义仍不能确定，不能伪报义项已解决。 |

来源：

- [IBTimes 对应文章](https://www.ibtimes.co.uk/dna-friendship-study-finds-we-are-genetically-linked-our-friends-1456676)
- [FT 对应文章](https://www.ft.com/content/95c62ecd-e0ca-4151-b3cf-8db4ee814137)
- [LUMI 官方供热说明](https://lumi-supercomputer.eu/the-waste-energy-of-lumi-supercomputer-produces-20-percent-of-the-district-heat-of-kajaani-csc-and-loiste-lampo-have-signed-an-agreement/)
- [Psychology Today 对应文章](https://www.psychologytoday.com/us/blog/the-clarity/202306/how-is-ai-changing-our-ideas-about-beauty)
- [Cambridge pace](https://dictionary.cambridge.org/us/dictionary/english/pace)

## 修改前确认的其他十处

五处单词阅读选项：fantastic、quiet、application、share、secure。两处词性或句法边界：mature、be。三处细义或程度边界：great，以及 2012、2008 年各一处 quite。

这十处是缺乏足够判别证据，不是词典缺失。五处来源事项的处理不能据此声称全库每个目标词均已唯一判义。

## 本次验收与恢复约束

1. 修改前保存所需文件和受影响记录的完整、可回读备份；范围、输入和修改前内容有 hash 守卫。
2. 两处文字校勘应用到同一原句的所有相关词卡、派生阅读文本；保留 sentence ID，更新真实显示 hash、字符范围和 chunk 联动，不凭旧校验结果跳过。
3. 错误 jug 归属只转移一次；若目标 juggle 已有同一位置，合并证据并去重，保持物理位置计数一致。
4. remote、pick 的整句语境说明与词典原义分开；as 仍保留具体不确定说明。来源与旧审查说明完整可看。
5. 检查重新执行幂等、预期内容不符时拒绝写入、恢复记录以及统计对账。
6. 实际打开两本书相关卡片，并分别检查两卷重排与整卷文本、chunk 标记及来源跳转。记录真实通过的范围，不据静态生成声称真机或 Anki 包通过。

## 实际数据结果

独立候选已应用 180 张既有词卡，每本书 90 张；134 条第一句记录完成文字与范围校勘，110 条后续句记录同步段落范围及来源哈希。两本书中的同一原卷位置从 `jug` 移到各自 `juggle` 卡，每本书只计一次。两书的 `number` 均保持 185 次，`jug` 由 1 次降为 0，`juggle` 由 4 次增为 5；全书物理出现次数不变。

ROOT 与独立复核均核对了实际活动快照和计数；原 v5 恢复库保持不变。14 张真实父卡的隔离应用、注入失败、重复应用、回退和完整恢复演练通过。数据回执见 [实际数据检查](evidence/source-confirmations-20261014-data.json)。源文件、语义数据库、整卷及重排页面的实际结果见配套 exam-library 的 `docs/evidence/source-confirmations-20261014-exam.json`。本地关键提交：Anki `61d8108`，exam-library `117fbc8`；未推送。

五处均已增加来源核验或校勘说明，其中四处完成校勘或语境解释。`as` 的原文字样已核实，具体义项仍未唯一确定；加上此前另十处，当前共十一处具体未决。报告保留修改前完整记录与实际两书快照绑定。

## 恢复应用代码

应用时的脚本与后续渲染脚本分别记录版本。原应用脚本的完整字节保存于 [已批准应用脚本归档](evidence/source-confirmations-20261014-approved-apply-driver.py)，SHA-256 为 `dcd2249383ef66d6e2a3ca7a610efa707dee76fd4d7009aba125510472a20981`。该归档的十四张真实卡片恢复演练通过。

若获授权回退实际候选，应先备份并校验当前渲染脚本，临时将该归档恢复到原路径 `scripts/apply_source_confirmations.py`，再以已应用计划的精确 SHA 运行 `rollback`，最后恢复当前脚本；不能直接从归档路径执行。原计划仍检查全部数据、来源和代码守卫。后续渲染改动使当前 CLI 与旧脚本哈希不同，未经这一步恢复会拒绝回退。此次未回退真实数据库。

## 实际网页验收

180 张受影响卡片全部生成并通过逐页反向还原检查；212 个当前原生例句的文字、目标范围及三种原卷链接参数核对通过。两本书的 `juggle` 默认例句均由四条补至五条，`jug` 默认例句已不含该转归位置。原有 66 份显示证书覆盖的 305 条细分更新完整保留。

ROOT 在当前 LAN 8771 页面实际检查了五处相关卡片说明、390px 手机尺寸与 1280px 桌面尺寸、两书从正面切换到答案及默认例句、年份筛选、英中细块联动、句内旧审查及完整历史详情。实点 2001 校正句的重排版和整卷版、2017 校正句的整卷版，以及字母插入后的 `items` 和同段下一句的 `return`：均接受精确句子来源定位，显示定位框且无拒绝提示。此前两卷的直接页面文字检查与截图仍有效，源文件随后未变。

书架仅替换了两本红宝书的“浏览全书”链接，保留原字节备份与可逆差异；ROOT 实点两入口，均加载到当前新版。完整证据及范围见 [本次网页验收记录](evidence/source-confirmations-20261014-web.json)。本次没有生成新 APKG、导入 Anki 或更新远端发布。
