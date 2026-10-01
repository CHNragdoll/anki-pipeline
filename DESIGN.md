---
name: "Anki · 全卡组预览"
description: "从当前源码提取的卡库外壳与原卡片视觉规则，不新增品牌方向。"
colors:
  primary: "#215fbb"
  primary-hover: "#1b509f"
  selected: "#edf3fc"
  shell-page: "#f4f6f9"
  shell-ink: "#273244"
  shell-muted: "#69778b"
  shell-line: "#dce2ea"
  surface: "#ffffff"
  card-page: "#f5f7fb"
  card-soft: "#edf3fb"
  card-ink: "#202b3c"
  card-secondary: "#47566c"
  card-muted: "#63718a"
  card-line: "#dce4ef"
  translation: "#6634a3"
  target: "#b51c83"
  target-soft: "#fbeaf4"
  night-page: "#151b25"
  night-surface: "#1d2634"
  night-soft: "#27394f"
  night-ink: "#e9edf5"
  night-secondary: "#b9c5d7"
  night-muted: "#a5b3c8"
  night-line: "#354459"
  night-primary: "#8dbaff"
  night-translation: "#664197"
  night-target: "#f695d4"
  night-target-soft: "#3b293a"
typography:
  display:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "3rem"
    fontWeight: 720
    lineHeight: 1.2
    letterSpacing: "-.025em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "1rem"
    fontWeight: 650
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "1.06rem"
    lineHeight: 1.75
  label:
    fontSize: ".85rem"
    fontWeight: 600
    lineHeight: 1.5
  phonetic:
    fontFamily: '"Charis SIL", "Times New Roman", serif'
    fontSize: "1.5rem"
rounded:
  navigation: "4px"
  control: "5px"
  number: "6px"
  front: "20px"
  meaning: "16px"
  example: "14px"
spacing:
  toolbar-gap: ".45rem"
  button-padding: ".35rem .65rem"
  word-padding: ".65rem .8rem"
  example-padding: "1.15rem 1.25rem 1rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "{spacing.button-padding}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  deck-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.primary}"
    rounded: "{rounded.navigation}"
    padding: ".5rem .55rem"
  front-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.card-ink}"
    rounded: "{rounded.front}"
    padding: "2.3rem 3.5rem 1.6rem"
  example-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.card-ink}"
    rounded: "{rounded.example}"
    padding: "{spacing.example-padding}"
  translation-tag:
    backgroundColor: "{colors.translation}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: ".02em .4em"
---

# Design System: Anki · 全卡组预览

## Overview

沿用 PRODUCT.md 已确认的“清晰、熟悉、专注”：目录与搜索承担浏览，卡片保留单词回忆和答案阅读的层级。界面以浅色背景、白色内容面、细分隔线和小范围语义色组织信息，不新增品牌比喻或装饰方向。

来源为 `anki_pipeline/templates/library-preview.css`、`style.css`，以及 `library-preview.js` 中仅作用于内嵌卡片的适配规则。本文是源码 Scan 记录，不代替最终浏览器验收。

**Key Characteristics:**
- 外壳紧凑，卡片正文宽松；两者使用独立根字号。
- 蓝色用于导航、主操作和编号；紫色标识译文；粉色标识目标词及原句跳转。
- 长词、释义和例句允许自然换行，移动目录可收起。

## Colors

### Primary

学习蓝使用 `primary`，用于主要按钮、选中目录、录音与查词入口、例句编号和卡片左侧细线。选中条目配合 `selected` 背景；外壳按钮悬停使用 `primary-hover`。

### Secondary

译文紫使用 `translation`，只承担翻译标签。目标粉使用 `target`，用于目标词高亮和原句跳转；跳转悬停配合 `target-soft`。目标词同时加粗（700），避免只依赖颜色。

### Neutral

外壳采用 `shell-*`，卡片采用 `card-*`；白色内容面使用 `surface`。保留两套已有中性色，不将相近值强行合并。卡片通过系统深色偏好或 Anki nightMode 切换至 `night-*`；外壳当前固定浅色，不宣称具有整页深色主题。

## Typography

外壳基准字号为 14px，标题为 `title`，单词列表名称为 1rem/600，释义摘要为 .8rem 且最多两行。数字计数采用等宽数字。卡片使用独立文档的宿主根字号，不继承外壳的 14px。

卡片单词使用 `display`；480px 及以下普通短词保持 2.3rem。仅内嵌 Web 预览中，标题含至少 12 个字母的拉丁词段时，`.word` 增加 `anki-preview-long-word` 类，在 480px 及以下使用 `font-size: clamp(1.125rem, 6vw, 2.3rem)`，减少长词碎行；该规则不改变共享 Anki 模板。音标使用 `phonetic`，窄屏缩至 1.3rem。核心释义为 1.22rem/600/1.65；英文例句为 1.12rem/1.7；译文为 1rem/1.85；出处为 .82rem 斜体。正文字段与标签使用 `body`、`label`。不引入额外字体资源。

## Layout

外壳占满视口高度（100vh / 100dvh），标题工具栏固定在上方，目录和词表各自滚动。宽屏为左侧 470px 浏览区和右侧剩余阅读区；浏览区内牌组列为 205px。901–1100px 时分别收紧到 405px、175px。

900px 及以下改为单阅读区，目录成为左侧抽屉（宽度 min(90vw, 500px)）；540px 及以下抽屉内部改为上下排列，牌组区为 minmax(140px, 36%)，词表使用剩余空间。

卡片最大内容宽度为 820px。内嵌预览对水平 padding 使用 clamp，并约束内容和媒体的 min-width / max-width。单词采用对称三列 inline-grid（44px / minmax(0, 1fr) / 44px，间距 .4rem），单词位于中列，查词按钮位于右列；避免长词因查词按钮而偏离中心。

卡片词形在 680px 及以上为两列，480px 及以下收紧字号和内边距，内嵌预览在 420px 及以下将词形名称和内容上下排列。阅读区使用定位 frame host 和满尺寸定位 iframe，为 Safari 提供明确视口。

## Elevation & Depth

大部分区域通过背景和一像素边线分层。卡片正面使用轻微阴影（`0 4px 16px rgb(26 48 84 / 4%)`）；移动抽屉使用横向阴影（`4px 0 24px rgb(20 35 58 / 12%)`）与半透明遮罩。牌组、词表和普通按钮没有额外浮起效果。

## Shapes

导航和控件使用小圆角，单词正面、释义容器和例句使用较大圆角。查词按钮是 44px 圆形；原句跳转入口是 40px 圆形，窄屏宽度为 36px、高度仍为 40px。例句保留蓝色 3px 左边线，不以新增装饰替代原来的颜色语义。

## Components

- **按钮**：外壳次操作为白底描边，主操作为蓝底白字；最小高度为 32px，移动外壳为 34px。卡片独立翻面按钮最小高度为 44px。
- **目录与词表**：选中项使用浅蓝背景；牌组同时变蓝、加粗，单词项增加蓝色左边线。词条保留名称、两行释义摘要和来源位置三层信息。
- **搜索**：白底小圆角描边输入框，带清空入口；外壳键盘焦点使用 2px 蓝色轮廓和 2px 间隔。
- **卡片**：正面保留居中单词、音标、录音及查词入口；答案保留释义、词形和完整例句。内嵌页隐藏自身翻面工具条，由外壳承担导航与翻面；卡片原有倒计时仍使用固定角落位置。
- **例句**：英文、译文和出处依次排列；编号为蓝底白字，译文标签为紫底白字。实际完形答案使用细实线下划线（1.5px、偏移 .16em）；目标词保留粉色加粗。
- **交互状态**：卡片链接悬停过渡为 160ms ease-out；卡片焦点为 3px 蓝色轮廓和 3px 间隔。减少动态偏好禁用卡片过渡/动画，并取消外壳平滑滚动。抽屉支持关闭、Escape 和键盘焦点约束；加载、空结果及错误重试保留文字状态。

## Do's and Don'ts

### Do:
- Do 保留蓝色编号、紫色翻译标签、粉色目标词和原句跳转的既有语义。
- Do 将外壳和内嵌卡片的根字号、响应式规则及主题范围分别处理。
- Do 保持单词中列居中、查词右列可见，并允许长内容换行。
- Do 保留可见键盘焦点和减少动态偏好的现有行为。

### Don't:
- Don't 把卡片正面与答案同时展开，或把欧路查词替换为 Anki 搜索。
- Don't 通过截断卡片正文或缩小全部文字来修复横向溢出。
- Don't 为当前 Scan 文档新增颜色、字体、品牌比喻或未实现组件。

## 已确认的词源卡片适配（2026-10-01）

用户确认 8782 演示后，将紧凑版词源区域接入正式网页及 APKG。顺序为真题词频、释义、考试等级、词根与词源、词形变化。词源正文从原卡片 `.form-row` 读取字号和行高；标题及标签读取原卡片对应样式，并通过只接收父窗口的消息传给独立词源文档。

保留原始词源正文、树、图片、同根词、例句和原查看器脚本。适配层只调整呈现：减少间距、去掉词源例句的“翻译”前缀和标签的 `#`，增加整批展开／收起例句。按用户追加要求，树保留原来的加减号、叶节点圆点及虚线，同根词保留左侧原圆形图标与虚线，不改成右侧箭头。内层文档按内容自动增高，不产生独立滚动条。完整内容可随外层卡片阅读区滚动。

适配资源为 `etymology-card.css` 和 `etymology-card.js`，嵌入每个离线词源文档，并参与不可变网页版本的指纹计算。无需 8782 或词典 API 服务。验收和备份位置见 `docs/ETYMOLOGY_CARD_UI.md`。
