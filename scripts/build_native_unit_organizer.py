"""Package the common opt-in desktop unit organizer for one explicit book map."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ENTRY = '''from aqt import mw
from aqt.qt import QAction
from aqt.utils import askUser,showInfo
from .native_units import plan_moves,apply_moves
from pathlib import Path
import json

ROOT=Path(__file__).parent
TITLE=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))['name']

def organize():
    try:
        mapping=json.loads((ROOT/'mapping.json').read_text(encoding='utf-8'))
        plan=plan_moves(mw.col,mapping)
        count=sum(map(len,plan['moves'].values()))
        if not count:
            showInfo('无需移动。已归组：%d；未找到或已自定义位置：%d。'%(plan['already'],len(plan['skipped'])))
            return
        if not askUser('将 %d 张已匹配卡片从原目录移动到新子牌组。\\n自定义位置与筛选牌组不动，不重置学习记录。\\n完成后可用“撤销”恢复。是否整理？'%count):return
        moved=apply_moves(mw.col,plan)
        mw.reset()
        showInfo('已整理 %d 张卡。学习记录保留。随后正常同步到手机即可。'%moved)
    except Exception as error:
        showInfo('整理未完成：'+str(error))

action=QAction(TITLE,mw)
action.triggered.connect(organize)
mw.form.menuTools.addAction(action)
'''


def build(mapping_path, output, *, book_id, title):
    mapping=json.loads(Path(mapping_path).read_text())
    if not isinstance(mapping,dict) or not mapping or any(
        not isinstance(k,str) or not isinstance(v,dict) or set(v)!={'from','to'}
        or any(not isinstance(v[p],str) or not v[p] for p in ('from','to')) for k,v in mapping.items()):
        raise ValueError('explicit nonempty native unit map required')
    manifest={'package':'study_unit_organizer_'+hashlib.sha256(book_id.encode()).hexdigest()[:16],
              'name':title,'min_point_version':50,'conflicts':[]}
    compile(ENTRY,'__init__.py','exec')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('__init__.py',ENTRY)
        archive.writestr('native_units.py',(Path(__file__).resolve().parents[1]/'anki_pipeline/study_catalog_native_units.py').read_bytes())
        archive.writestr('mapping.json',json.dumps(mapping,ensure_ascii=False))
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mapping',required=True);p.add_argument('--output',required=True);p.add_argument('--book-id',required=True);p.add_argument('--title',required=True)
    a=p.parse_args();build(a.mapping,a.output,book_id=a.book_id,title=a.title)
