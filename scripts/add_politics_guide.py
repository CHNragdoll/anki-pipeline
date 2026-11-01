"""Append one stable, standalone guide to the current complete politics APKG."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

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
CSS = '''.card{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:18px;line-height:1.8;text-align:left;color:#243247;background:#f5f7fc;margin:0;padding:24px}.guide{max-width:760px;margin:0 auto;background:white;border:1px solid #e1e7f0;border-radius:18px;padding:28px}h1{font-size:27px;margin:0 0 8px}h2{font-size:19px;color:#285da8;margin:24px 0 6px}p{margin:0 0 12px}.intro,.footer{color:#697b93}.footer{border-top:1px solid #e1e7f0;padding-top:16px;margin-top:24px;font-size:15px}@media(max-width:500px){.card{padding:12px;font-size:17px}.guide{padding:20px}}.nightMode .guide{background:#202733;color:#e1e7f0}.nightMode.card{background:#151a22;color:#e1e7f0}'''


def build(source, target):
    source, target = Path(source), Path(target)
    if target.exists():
        raise ValueError('Destination already exists')
    now = int(time.time())
    with zipfile.ZipFile(source) as original, tempfile.TemporaryDirectory() as tmp:
        path = Path(original.extract('collection.anki2', tmp))
        with sqlite3.connect(path) as db:
            tables = ('notes', 'cards', 'revlog', 'graves')
            before = {t: db.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in tables}
            models_raw, decks_raw = db.execute('SELECT models,decks FROM col').fetchone()
            models, decks = json.loads(models_raw), json.loads(decks_raw)
            assert str(MODEL_ID) not in models and str(DECK_ID) not in decks
            assert not db.execute('SELECT 1 FROM notes WHERE guid=? OR id=?', (GUID, NOTE_ID)).fetchone()
            model = copy.deepcopy(next(iter(models.values())))
            model.update(id=MODEL_ID,name=ROOT+' · 使用说明',did=DECK_ID,mod=now,type=0,sortf=0,usn=-1,
                         css=CSS,tags=[],req=[[0,'all',[0]]])
            field = copy.deepcopy(model['flds'][0])
            model['flds'] = [dict(field,name=name,ord=i) for i,name in enumerate(('Title','Instructions'))]
            template = copy.deepcopy(model['tmpls'][0])
            template.update(name='使用说明',ord=0,qfmt='<section class="guide"><h1>{{Title}}</h1><p>翻面查看使用方法、题型结构与更新说明。</p></section>',afmt='{{Instructions}}',bqfmt='',bafmt='',did=None)
            model['tmpls'] = [template]
            deck = copy.deepcopy(next(d for d in decks.values() if d['name'].startswith(ROOT+'::')))
            deck.update(id=DECK_ID,name=ROOT+'::00 使用说明',desc='独立使用说明，不计入真题数量。',mod=now,usn=-1)
            models[str(MODEL_ID)], decks[str(DECK_ID)] = model, deck
            db.execute('UPDATE col SET models=?,decks=?',(json.dumps(models,ensure_ascii=False),json.dumps(decks,ensure_ascii=False)))
            checksum = int(hashlib.sha1(TITLE.encode()).hexdigest()[:8],16)
            db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)',(NOTE_ID,GUID,MODEL_ID,now,-1,' 使用说明 ',TITLE+'\x1f'+BODY,TITLE,checksum,0,''))
            db.execute('INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(CARD_ID,NOTE_ID,DECK_ID,0,now,-1,0,0,1,0,0,0,0,0,0,0,0,''))
            db.commit()
            for table in tables:
                actual = db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                if table in ('notes','cards'):
                    actual = [row for row in actual if row[0] != (NOTE_ID if table=='notes' else CARD_ID)]
                assert actual == before[table], table
            for key,value in json.loads(models_raw).items(): assert models[key] == value
            for key,value in json.loads(decks_raw).items(): assert decks[key] == value
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert db.execute('SELECT count(*) FROM cards').fetchone()[0]==833
        with zipfile.ZipFile(target,'w') as output:
            for member in original.infolist():
                output.writestr(copy.copy(member),path.read_bytes() if member.filename=='collection.anki2' else original.read(member))
        with zipfile.ZipFile(target) as result:
            assert result.testzip() is None
            for name in original.namelist():
                if name!='collection.anki2': assert original.read(name)==result.read(name)
    return dict(cards=833,questions=832,guide_cards=1,guide_deck=ROOT+'::00 使用说明',existing_rows_templates_and_media_unchanged=True,bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())

if __name__=='__main__':
    import sys
    print(json.dumps(build(*sys.argv[1:]),ensure_ascii=False,indent=2))
