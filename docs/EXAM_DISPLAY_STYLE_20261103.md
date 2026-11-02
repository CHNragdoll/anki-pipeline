# 政治、408 与数学三排版同步验收

本轮仅统一公式显示、选项对齐和数学三全角 ASCII。未发布 GitHub Release。

| 内容 | 新完整包 | 验收 |
| --- | --- | --- |
| 政治 | Politics-Past-Exams-Full-20261103.apkg，833 张，3,243,233 字节 | 28 处可见公式入口均有 displaystyle |
| 408 | CS408-Past-Exams-Full-20261103.apkg，800 张，63,478,517 字节 | 1,750 处可见公式入口均有 displaystyle |
| 数学三 | Math3-Past-Exams-Full-20261103.apkg，1,061 张 | 题干、选项、详解可见全角 ASCII 残留 0；中文标点保留 |

政治、408 从总库统一投影重新导出；保留当前完整包的原说明卡、牌组名称及每张卡的牌组归属。Question/Answer 与当前完整包逐项比较仅允许现有 formatter 的显示整理，其余字段逐字一致；本次实际比较两个完整基线的正文已具备 displaystyle，无正文新增改写。补齐的是统一 CSS、重导出及旧书架路由。

原生 Anki 在独立临时集合导入旧完整包，制造复习记录、暂停和标记后覆盖新版并重复导入；政治、408 均保持笔记/卡片数量、身份、调度、标记和 revlog。政治全量核对 4,994 字段、7 个媒体；408 核对 4,796 字段、184 个媒体，SHA 核对通过，无缺失媒体。没有写入个人 Anki 资料档案。

Safari 实际查看政治 2003 第 6 题的表格分数和选项、408 2012 第 1 题的公式选项与彩色代码；截图保存在对应 output 交付目录的 screenshots。手机端未做本轮实机验收。

原书架政治和 408 的逐题/整卷 URL 保持不变，指向本轮导出；旧网页以 web-before-displaystyle-20261103 留一份回滚。书架完整包下载已更新到上述新版，HTTP 检查通过。

证据： [本轮完整验收目录](evidence/exam-displaystyle-20261103)。生成脚本：scripts/update_exam_display_style.py。PG 写前备份路径和 SHA 见 receipt；没有修改 SourceRecord、原题/媒体身份、其他书或学习进度表。
