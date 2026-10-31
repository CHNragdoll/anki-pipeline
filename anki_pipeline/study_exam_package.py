"""Produce an immutable question-bank input for the common package importer.

This is a source-format adapter. Final Web and Anki deliveries must both come
from study_catalog_export, never directly from this intermediate collection.
"""
from __future__ import annotations
import hashlib
from contextlib import closing
import html
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

FIELDS = ('Title', 'Question', 'Answer', 'Source', 'Status', 'SourceRecord')
# Shared authored interaction: both Web and Anki execute this exact template.
CHOICE_SCRIPT = r"""<script>(function(){
  var clean=function(s){return s.replace(/\s+/g,'');};
  document.querySelectorAll('.exam-notecard').forEach(function(root){
    if(root.dataset.choiceReady)return;
    var heading=root.querySelector('.exam-identity');if(!heading)return;
    var key='exam-choice-v1:'+heading.textContent.trim(), picked=[];
    try{picked=JSON.parse(sessionStorage.getItem(key)||'[]');}catch(e){}
    if(!Array.isArray(picked))picked=[];
    if(root.classList.contains('exam-answer')){
      root.dataset.choiceReady='true';
      return;
    }
    var data=root.querySelector('.exam-selection-source'),record;
    if(!data)return;
    try{record=JSON.parse(data.textContent).question;}catch(e){return;}
    var type=record.questionType, options=record.options||[];
    if((type!=='single_choice'&&type!=='multiple_choice')||!options.length)return;
    var body=root.querySelector('.exam-body'), nodes=Array.from(body.querySelectorAll('.choice'));
    // Some source editions put several options in one plain paragraph. Replace
    // only a complete, exact text match; never guess boundaries in the stem.
    if(nodes.length!==options.length){
      var parts=options.map(function(o){return (o.sourceLabel||o.label)+' '+o.text;});
      var paragraphs=Array.from(body.querySelectorAll('p')),matched=[],cursor=0;
      paragraphs.forEach(function(p){
        if(p.children.length||cursor>=options.length)return;
        for(var stop=cursor+1;stop<=options.length;stop++){
          if(clean(p.textContent)===clean(parts.slice(cursor,stop).join(' '))){matched.push([p,cursor,stop]);cursor=stop;break;}
        }
      });
      if(cursor===options.length){
        matched.forEach(function(m){var group=document.createElement('div');group.className='choices';
          options.slice(m[1],m[2]).forEach(function(o){var row=document.createElement('div');row.className='choice';var label=document.createElement('b'),text=document.createElement('span');label.textContent=o.sourceLabel||o.label;text.textContent=o.text;row.append(label,text);group.append(row);});m[0].replaceWith(group);
        });
        nodes=Array.from(body.querySelectorAll('.choice'));
      }
    }
    if(nodes.length!==options.length)return;
    root.dataset.choiceReady='true';
    var multi=type==='multiple_choice',labels=options.map(function(o){return String(o.label).replace(/[^A-Za-z0-9]/g,'');});
    picked=picked.filter(function(v){return labels.indexOf(v)>=0;});if(!multi)picked=picked.slice(0,1);
    var controls=document.createElement('div');controls.className='exam-pick-controls';
    var status=document.createElement('span');status.className='exam-pick-status';status.setAttribute('aria-live','polite');
    var reset=document.createElement('button');reset.type='button';reset.className='exam-clear-choice';reset.textContent='清除选择';controls.append(status,reset);body.after(controls);
    var paint=function(){nodes.forEach(function(n,i){var yes=picked.indexOf(labels[i])>=0;n.classList.toggle('exam-choice-selected',yes);n.setAttribute('aria-checked',String(yes));});status.textContent=picked.length?'已选：'+picked.join('、')+' · 翻面查看答案':(multi?'多选题：可选择多个选项':'单选题：请选择一个选项');reset.disabled=!picked.length;try{sessionStorage.setItem(key,JSON.stringify(picked));}catch(e){}};
    var choose=function(i){var label=labels[i];if(multi){picked=picked.indexOf(label)>=0?picked.filter(function(v){return v!==label;}):picked.concat([label]);picked.sort(function(a,b){return labels.indexOf(a)-labels.indexOf(b);});}else{picked=[label];}paint();};
    body.setAttribute('role',multi?'group':'radiogroup');body.setAttribute('aria-label',multi?'多选题选项':'单选题选项');
    nodes.forEach(function(n,i){n.classList.add('exam-choice-interactive');n.setAttribute('role',multi?'checkbox':'radio');n.tabIndex=0;
      n.addEventListener('click',function(e){e.stopPropagation();choose(i);});
      n.addEventListener('keydown',function(e){if(e.key===' '||e.key==='Enter'){e.preventDefault();e.stopPropagation();choose(i);}else if(!multi&&['ArrowDown','ArrowRight','ArrowUp','ArrowLeft'].indexOf(e.key)>=0){e.preventDefault();e.stopPropagation();var next=(i+(e.key==='ArrowDown'||e.key==='ArrowRight'?1:nodes.length-1))%nodes.length;nodes[next].focus();choose(next);}});
    });
    reset.addEventListener('click',function(e){e.stopPropagation();picked=[];paint();});paint();
  });
})();</script>"""
FRONT = '<div class="exam-location">{{Title}}</div><article class="exam-notecard"><span class="exam-identity" hidden>{{Title}}</span><div class="exam-body">{{Question}}</div><div class="exam-selection-source" hidden>{{SourceRecord}}</div></article>' + CHOICE_SCRIPT
BACK = '{{FrontSide}}<article id="answer" class="exam-notecard exam-answer" data-answer-status="{{Status}}"><span class="exam-identity" hidden>{{Title}}</span><header class="exam-answer-heading">答案与解析</header><div class="exam-body">{{Answer}}</div><footer class="exam-source">{{Source}}</footer><details class="exam-audit"><summary>来源与原始记录</summary><pre>{{SourceRecord}}</pre></details></article>' + CHOICE_SCRIPT

CSS = '''.card{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:18px;line-height:1.85;color:#243248;background:#f5f7fb;text-align:left;margin:0;padding:12px;overflow-wrap:break-word}.exam-notecard{box-sizing:border-box;max-width:920px;margin:14px auto 24px;padding:26px 30px;background:white;border:1px solid #dce5f1;border-radius:16px}.exam-heading{padding-bottom:15px;margin-bottom:18px;border-bottom:1px solid #e5ebf3}.exam-heading>span{font-size:13px;font-weight:600;color:#5374a5;letter-spacing:.04em}.exam-heading h1{font-size:20px;line-height:1.5;margin:8px 0 0}.exam-body p{margin:.8em 0}.exam-body h2,.exam-body h3{font-size:18px;margin:1.4em 0 .6em}.choices{display:grid;gap:10px;margin:18px 0}.choice{display:flex;gap:12px;padding:10px 14px;background:#f7f9fc;border:1px solid #e5ebf3;border-radius:8px}.choice>b{flex:none;color:#355b91}.choice>span{min-width:0}.exam-body img{display:block;max-width:100%;height:auto;margin:16px auto}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #dce5f1;padding:8px 12px;vertical-align:top}.exam-answer{border-top:3px solid #527bb5}.exam-missing,.exam-answer[data-answer-status=missing]{border-color:#d9b876}.exam-missing{padding:15px;background:#fff9e9;border:1px solid #e5cf9a;border-radius:8px;color:#805f24}.exam-source{font-size:13px;color:#718198;margin-top:24px;padding-top:14px;border-top:1px solid #e5ebf3}.exam-audit{font-size:12px;color:#718198;margin-top:16px}.exam-audit summary{cursor:pointer}.exam-audit pre{white-space:pre-wrap;word-break:break-word;max-height:440px;overflow:auto}.nightMode.card,.night_mode.card{background:#181d25;color:#e2e7ef}.nightMode .exam-notecard,.night_mode .exam-notecard{background:#232b36;border-color:#3d4a5c}.nightMode .choice,.night_mode .choice{background:#2b3544;border-color:#3d4a5c}@media(max-width:600px){.card{padding:8px;font-size:17px}.exam-notecard{padding:20px 18px;border-radius:12px}.exam-heading h1{font-size:18px}}'''
CSS += '.exam-selection-source[hidden]{display:none!important}.exam-choice-interactive{cursor:pointer;touch-action:manipulation;transition:border-color .12s,background-color .12s}.exam-choice-interactive:hover{border-color:#9bb9e5}.exam-choice-interactive:focus-visible{outline:3px solid #5c8ed3;outline-offset:2px}.exam-choice-selected{background:#e4edff!important;border-color:#386ec2!important;box-shadow:inset 3px 0 #386ec2}.exam-pick-controls{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:18px}.exam-pick-status{font-size:14px;color:#47648e}.exam-clear-choice{font:inherit;font-size:14px;border:1px solid #cddbed;background:#fff;color:#355f9c;border-radius:8px;padding:7px 12px;cursor:pointer}.exam-clear-choice:disabled{opacity:.45;cursor:default}.nightMode .exam-choice-selected,.night_mode .exam-choice-selected{background:#263f64!important}.nightMode .exam-clear-choice,.night_mode .exam-clear-choice{background:#232b36;color:#b7d2fb}'



def _number(namespace, key):
    return int(hashlib.sha256((namespace + '\0' + key).encode()).hexdigest()[:8], 16) % 2_147_483_646 + 1


def source_package(snapshot, destination, *, book_id, title):
    import genanki
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('source package already exists; preserve its native identities')
    destination.parent.mkdir(parents=True, exist_ok=True)
    model = genanki.Model(_number('exam-model', 'v1'), '整卷真题 · 通用题目 v1',
        fields=[{'name': name} for name in FIELDS], templates=[{'name': '题目 → 答案解析', 'qfmt': FRONT, 'afmt': BACK}], css=CSS)
    decks = {}; missing = []
    seen = set()
    for row in snapshot['questions']:
        if row['key'] in seen:
            raise ValueError('duplicate exam question identity')
        seen.add(row['key'])
        year = str(row['year'])
        if year not in decks:
            decks[year] = genanki.Deck(_number('exam-unit', book_id + ':' + year), title + '::' + year + ' 年')
        source = html.escape(row['source_label']) + '<br>题目 ID：' + html.escape(row['key'])
        fields = [html.escape(row['title']), row['question'], row['answer'], source, row['status'],
                  html.escape(json.dumps(row['source_record'], ensure_ascii=False, separators=(',', ':')))]
        guid = genanki.guid_for('anki-pipeline/exam-question/v1', book_id, row['key'])
        note = genanki.Note(model=model, fields=fields, guid=guid,
                           tags=['exam', 'year::' + year, row['type'], 'answer::' + row['status']])
        decks[year].add_note(note)
        if row['status'] != 'available':
            missing.append(guid)
    resources = snapshot['resources']
    for alias, resource in resources.items():
        raw = Path(resource['path']).read_bytes()
        if len(raw) != resource['bytes'] or hashlib.sha256(raw).hexdigest() != resource['sha256']:
            raise ValueError('source media changed')
    with tempfile.TemporaryDirectory(prefix='exam-source-') as temporary:
        root = Path(temporary); media = root / 'media'; media.mkdir()
        files = []
        for alias, resource in resources.items():
            path = media / alias; path.write_bytes(Path(resource['path']).read_bytes()); files.append(str(path))
        raw_package = root / 'source.apkg'
        package = genanki.Package(list(decks.values())); package.media_files = files
        package.write_to_file(str(raw_package), timestamp=int(time.time()))
        with zipfile.ZipFile(raw_package) as archive:
            collection = root / 'collection.anki2'; collection.write_bytes(archive.read('collection.anki2'))
            with closing(sqlite3.connect(collection)) as db, db:
                for guid in missing:
                    db.execute('UPDATE cards SET queue=-1 WHERE nid IN (SELECT id FROM notes WHERE guid=?)', (guid,))
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('source collection integrity failed')
                notes = db.execute('SELECT count(*) FROM notes').fetchone()[0]
                cards = db.execute('SELECT count(*) FROM cards').fetchone()[0]
                assert notes == cards == len(seen)
            with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for entry in archive.infolist():
                    output.writestr(entry.filename, collection.read_bytes() if entry.filename == 'collection.anki2' else archive.read(entry.filename))
    with destination.open('rb') as stream:
        package_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'book_id': book_id, 'notes': len(seen), 'cards': len(seen), 'years': len(decks), 'media': len(resources),
            'missing_answer_suspended': len(missing), 'source_sha256': snapshot['source_sha256'],
            'package_sha256': package_sha256, 'bytes': destination.stat().st_size}

CSS += ' .exam-identity[hidden]{display:none!important}.exam-location{box-sizing:border-box;max-width:920px;margin:16px auto 8px;padding:0 4px;text-align:right;color:#718198;font-size:14px;line-height:1.6}.exam-answer-heading{font-size:16px;font-weight:600;color:#5374a5;margin-bottom:16px}.exam-location+.exam-notecard{margin-top:8px}'
