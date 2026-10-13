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

本文件是修改范围及验收计划，尚不是完成记录。实际结果另附证据。
