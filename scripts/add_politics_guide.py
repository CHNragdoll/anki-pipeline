"""Append one stable, standalone guide to the current complete politics APKG."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anki_pipeline.study_exam_guide import (
    GUIDE_CSS, GuideCollisionError, GuideIdentity, add_guide,
)

GUID = 'PolGuide01'
MODEL_ID = 1911002001
DECK_ID = 1911002002
NOTE_ID = 1793548800001
CARD_ID = 1793548800002
ROOT = '考研政治历年真题'
TITLE = '考研政治历年真题 · 使用说明'
BODY = '''<section class="guide"><h1>使用说明</h1>
<p class="intro">2003—2024 年 · 832 道真题</p>
<h2>牌组结构</h2><p>题目按“年份 → 单选题／多选题／材料分析题”划分；本说明单独放在“使用说明”子牌组。</p>
<h2>选择与查看答案</h2><p>点击选项进行选择，再点同一选项可取消。多选题可选择多个选项。选择选项不会自动翻面；完成选择后，点击“查看答案”或客户端的“显示答案”。</p>
<h2>答案与解析</h2><p>背面保留完整题目，在题目下方显示答案与解析；正确选项标绿，已选错误选项标红。进入下一题时，选择状态应为空。材料分析题可先自行作答，再查看参考答案。</p>
<h2>手机与平板</h2><p>AnkiMobile 使用卡片中的“查看答案”按钮时，请将“偏好设置 → 复习 → 点按”里的正面中央区域配置为“显示答案”。</p>
<h2>更新与学习记录</h2><p>后续更新请直接导入完整新版，避免为了更新而删除旧牌组。更新包保留原题身份；实际导入时留意客户端的更新提示。学习进度由 Anki 管理。</p>
<h2>内容说明</h2><p>本包保留原题与参考解析，历史试题反映命题当年的语境。已清理广告与错误硬换行；“考点知识还原”、内部题目 ID 和来源记录不在卡片正文中展示。</p>
<p class="footer">本说明卡不计入 832 道真题；完整包共 833 张卡。</p></section>'''
CSS = GUIDE_CSS


def build(source, target):
    # These IDs and the original BODY/CSS are an established import contract.
    try:
        result = add_guide(
            source, target, book_id='politics-exams', root=ROOT,
            question_count=832, guide_html=BODY, title=TITLE, css=CSS,
            identity=GuideIdentity(GUID, MODEL_ID, DECK_ID, NOTE_ID, CARD_ID),
        )
    except GuideCollisionError as error:
        # Preserve the original helper's duplicate-guide exception contract.
        raise AssertionError(str(error)) from error
    result.pop('guide_identity')
    return result


if __name__=='__main__':
    import sys
    print(json.dumps(build(*sys.argv[1:]),ensure_ascii=False,indent=2))
