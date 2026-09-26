# 本地重建计划

用户授权：在 Anki 目录优化重建 V2.0，修复评估问题；可使用 gpt-6-sol xhigh/ultra 子代理。
任务：首次标准采纳 + change（type=refactor，risk=R2，含 bug fixes / 数据迁移）。
用户后续追加授权：创建远端私人仓库，按 tag/version/labels 流程交付，并提供 Markdown 对应截图与素材目录；时间直接在聊天中报告。
交付更新：私人仓库 formal-version-delivery，首个重建候选版 v3.0.0-rc.1，真实 PR 审查后合入 main，再从合入提交创建 tag / prerelease。
仅在 anki_rebuild 写入；V2.0、旧数据库、原始音频、已有 apkg 均为只读输入。不导入用户 Anki 集合；远端不上传词库/音频/真题/生成卡包。

## 架构与接口

Python 包 anki_pipeline，统一 CLI / TOML 配置，SQLite 版本化存储，纯函数处理文本，独立 HTML/CSS/JS 模板。
数据库 cards 字段：id,sheet,lesson,position,word,phonetic,definition,simple_definition,level,word_forms,audio_filename。
sentences 字段：id,card_id,text,source,translation,original_number,accepted,review_reason。
保留原始来源快照与全部句子（包括被拒绝的误命中），不编造缺失翻译。
卡片字典传递给打包模块，额外 examples=[{text,source,translation}]；音频目录独立传入。

## 实施顺序

1. 固定旧输入摘要；建立新目录、版本控制、配置、标准适用性记录。
2. 并行：精确词形与例句/译文纯函数；安全 Anki 打包和模板；词表及词典输入模块。
3. 集成新 SQLite 存储、只读旧库迁移、ID 对齐的翻译交换、CLI、备份/恢复与校验。
4. 真实 1,960 词迁移与修复分类、重跑对账、生成新 apkg 和待处理清单。
5. 单元/集成/回滚/产物检查、模板渲染、一次独立审查；记录局限与运行命令。

## 验收

- 原始输入哈希不变；新库迁移保留全部词条与原始句子，误命中隔离可追溯。
- rate 不命中 rather/rat；theme 不命中 them；fee 不命中 feel；支持明确词形。
- 翻译按稳定句子 ID 导入；编号解析重复/缺失报错或生成明确问题，不按行盲配。
- 重跑不增加重复记录/译文；失败写入回滚保留旧数据；备份可恢复并对账。
- 打包牌组/笔记 ID 跨进程稳定；媒体引用有效；脚本不混入 CSS；无硬编码过期倒计时。
- 提供新词表、PDF 提取、可选网络补全、翻译导入导出、校验和打包命令。
- 实际 Anki 手机/桌面导入兼容性如未执行，必须标明 NOT_RUN；不声称正式发布或全标准通过。
