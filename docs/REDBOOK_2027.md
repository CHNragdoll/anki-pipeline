# 2027 红宝书交付记录

记录日期：2026-10-06。牌组名称为 **2027考研英语红宝书（必考词+基础词+超纲词）真题例句版**。

## 正式发布与下载

2026-10-06 已发布 [redbook-2027.10.06 正式版](https://github.com/CHNragdoll/anki-pipeline/releases/tag/redbook-2027.10.06)，标签绑定合并提交 `71ff9ab68b10974270e5bf769a156da94c661780`。

- [完整 APKG](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2027.10.06/2027-RedBook-Full-Audio-Completed-20261006.apkg)
- [交付报告](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2027.10.06/2027-RedBook-Report-20261006.md)
- [核验 JSON](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2027.10.06/2027-RedBook-Verification-20261006.json)
- [SHA-256 清单](https://github.com/CHNragdoll/anki-pipeline/releases/download/redbook-2027.10.06/2027-RedBook-SHA256-20261006.txt)

已完整回下载公开 APKG，逐字节摘要与下表一致，ZIP 与媒体引用核验通过。四个远端附件摘要均与上传输入一致；发布为非草稿、非预发布。保留已有刘晓艳和 2026 标签、附件。

## 卡包核对

本记录绑定完成录音补齐的兼容 APKG，文件名为 `2027考研英语红宝书（必考词+基础词+超纲词）真题例句版.apkg`：

| 项目 | 核对结果 |
| --- | --- |
| SHA-256 | `86843d8d71342ad6b5a80b8a3235e0164d7f1e549e41dbe1252d0c46077a9c40` |
| 文件大小 | 187,276,604 字节 |
| 卡片 | 6,530 张，包含 6,529 张词汇卡和 1 张说明卡 |
| 有卡分组 | 82 个；包内还包含父牌组及默认牌组，共 89 条牌组记录 |
| 媒体 | 27,579 个，保留此前 27,568 个，新增 11 个录音 |
| 明确口音的录音缺口 | 英式 0、美式 0；引用文件缺失 0 |

说明卡置于 `00 牌组说明`，其后依次为必考词、基础词及按字母分组的超纲词。保留原词表顺序和连续编号；新导入的开头是说明卡、`radiate`、`radiant`、`radical`、`object`。基础词 Unit 31 在 `a/an` 处分成“简单基础词之一”和“简单基础词之二”。

显示用的“必考词/基础词”去掉原 A/B 前缀，Anki 内部用 `01/02` 保持分组次序。音标与音频分别记录来源，选择口音及词典的方式见 [发音与导出协议](REDBOOK_EXPORT.md)。

## 本次补充录音

| 词 | 口音 | 核对来源 |
| --- | --- | --- |
| according | 英、美 | [牛津 OED](https://www.oed.com/dictionary/according_adj) |
| arrestee | 英 | [牛津 OED](https://www.oed.com/dictionary/arrestee_n) |
| longline | 英 | [牛津 OED 的 long line 词条](https://www.oed.com/dictionary/long-line_n) |
| low-density | 英、美 | [牛津 OED](https://www.oed.com/dictionary/low-density_adj) |
| native-born | 英 | [牛津 OED](https://www.oed.com/dictionary/native-born_adj) |
| technicist | 英、美 | [牛津 OED](https://www.oed.com/dictionary/technicist_n) |
| transcendentalist | 英 | [牛津 OED](https://www.oed.com/dictionary/transcendentalist_n) |
| open-access | 美 | 本地牛津高阶；[对应官网词条](https://www.oxfordlearnersdictionaries.com/definition/english/open-access) |

共 8 个词、11 个口音：OED 10 个，本地牛津高阶 1 个。来源页、完整原录音及来源绑定保存在共享本地索引中，后续书籍可以复用。未用相近词录音或合成语音替代。`according` 的首选来源无录音时，按钮使用已核对的牛津录音并显示回退提示。

仅更新这 8 条笔记的 Audio 字段，原音标保持。卡片的“补充录音来源与读法”提供来源页及其读法，注明来源页与卡片音标可能使用不同标注方式。

## 核验记录与边界

本地核验包括包内媒体与明确口音覆盖审计、11 处浏览器播放、来源页绑定、共享索引重复导入不新增记录，以及隔离 Anki 环境的新导入、覆盖更新、重复导入。覆盖更新保留原排序、复习记录与暂停状态；重复导入不增加重复卡。词根折叠样式另对实际词典页面核对全文、顺序、原链接和换行保留。本次源码摘要与本地核验记录一致；成品 CSS 还保留本地构建的 `overflow: hidden` → `overflow: auto` 归一化，JS 保留源码内容。

这些是绑定上述 APKG 摘要的本地核验记录，原始核验文件留在受控构建目录，未将词表、词典全文、录音及个人集合加入 Git。此次提交纳入共享词根样式及其回归测试，并记录 2027 成品状态；它不包含从原始 CSV 一键重做全部离线词典资源的构建器。

没有操作用户实际 Anki 集合；未以隔离导入或浏览器结果代替手机真机验收、整个账户的 AnkiWeb 同步验收。原源码提交与发布分开执行；正式发布地址与远端摘要核验现已补在本页上方。2026-10-06 新增界面截图的具体设备与版本范围见 [README 证据记录](README_EVIDENCE_20261006.md)，其中现有华为刘晓艳牌组截图不作为本包手机验收。
