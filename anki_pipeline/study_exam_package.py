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

from .study_exam_source import question_type_labels

FIELDS = ('Title', 'Question', 'Answer', 'Source', 'Status', 'SourceRecord')
# Shared authored interaction: both Web and Anki execute this exact template.
CHOICE_SCRIPT = r"""<script>(function(){
 function initialize(){
  // The common source marks only page-edge continuations verified by geometry.
  // Scope to each body so FrontSide and answer copies cannot share a flow.
  document.querySelectorAll('.exam-body').forEach(function(body){
    var flows=new Map();
    body.querySelectorAll('p[data-paragraph-flow]').forEach(function(node){
      var key=node.dataset.paragraphFlow,left=flows.get(key);
      if(!key)return;
      if(!left){flows.set(key,node);return;}
      while(node.firstChild)left.append(node.firstChild);
      node.remove();
    });
  });
  document.querySelectorAll('.exam-location').forEach(function(path){path.textContent=path.textContent.replace(/\s*·\s*/g,' ➫ ');});
  // Preserve source table references in fields/audit, while omitting this
  // section from both learning surfaces and retaining neighboring sections.
  document.querySelectorAll('.exam-answer .exam-body > h2').forEach(function(heading){
    if(heading.textContent.replace(/[\s【】]/g,'')!=='考点知识还原')return;
    var node=heading;
    do{node.hidden=true;node.classList.add('exam-omitted-section');node=node.nextElementSibling;}while(node&&!/^H[12]$/.test(node.tagName));
  });
  // Native AnkiMobile/AnkiDroid must pass taps to this authored surface instead
  // of interpreting every option, paragraph or blank area as a review gesture.
  var guard=window.__ankiExamSurfaceGuardV1;
  if(guard&&guard.body!==document.body){guard.cleanup();guard=null;}
  if(!guard){
    var surface=document.body,html=document.documentElement,oldBodyTap=surface.classList.contains('tappable'),oldHtmlTap=html.classList.contains('tappable'),oldHeight=surface.style.minHeight;
    var block=function(e){if(document.querySelector('.exam-notecard'))e.stopPropagation();};
    var observer=new MutationObserver(function(){if(!document.querySelector('.exam-notecard'))guard.cleanup();});
    guard={body:surface,cleanup:function(){observer.disconnect();surface.removeEventListener('click',block);if(!oldBodyTap)surface.classList.remove('tappable');if(!oldHtmlTap)html.classList.remove('tappable');surface.style.minHeight=oldHeight;if(window.__ankiExamSurfaceGuardV1===guard)delete window.__ankiExamSurfaceGuardV1;}};
    window.__ankiExamSurfaceGuardV1=guard;surface.addEventListener('click',block);observer.observe(html,{childList:true,subtree:true});
    html.classList.add('tappable');surface.classList.add('tappable');surface.style.minHeight='100vh';
  }
  document.querySelectorAll('.exam-location,.exam-notecard,.exam-notecard *').forEach(function(n){n.classList.add('tappable');});
  var clean=function(s){return s.replace(/\s+/g,'');};
  var following=function(root){var n=root.nextElementSibling;while(n&&n.tagName==='SCRIPT')n=n.nextElementSibling;return n;};
  document.querySelectorAll('.exam-notecard').forEach(function(root){
    var reveal=root.querySelector('.exam-reveal'),next=following(root);
    if(reveal&&next&&next.classList.contains('exam-answer'))reveal.hidden=true;
    if(root._examChoicePaint){
      root._examChoicePaint();
      if(next&&next.matches('details.paper-answer')&&root._examLinkedDetail!==next){next.addEventListener('toggle',root._examChoicePaint);root._examLinkedDetail=next;}
    }
    if(root.dataset.choiceReady)return;
    var heading=root.querySelector('.exam-identity');if(!heading)return;
    if(root.classList.contains('exam-answer')){root.dataset.choiceReady='true';return;}
    var data=root.querySelector('.exam-selection-source'),record;
    if(!data)return;
    var source;try{source=JSON.parse(data.textContent);record=source.question;}catch(e){return;}
    var body=root.querySelector('.exam-body'),number=String(record.number||'');
    // Source-page boundaries are layout, not paragraph boundaries. Join only
    // an explicitly same-question Han-word continuation on the next source page.
    var blocks=source.question_blocks||[],mapped=new Map(),joins=0;
    blocks.forEach(function(b){
      var raw;try{raw=JSON.parse(b.raw_json);}catch(e){return;}
      var parsed=new DOMParser().parseFromString(b.content_html||raw.contentHtml||'','text/html');
      var children=Array.from(parsed.body.children);
      if(children.length!==1||!children[0].matches('p.paragraph')||children[0].querySelector('img,table,math'))return;
      var text=clean(children[0].textContent),matches=Array.from(body.children).filter(function(n){return n.matches('p.paragraph')&&clean(n.textContent)===text;});
      if(matches.length===1)mapped.set(b.id,{node:matches[0],raw:raw,text:children[0].textContent.trim()});
    });
    for(var bi=1;bi<blocks.length;bi++){
      var left=mapped.get(blocks[bi-1].id),right=mapped.get(blocks[bi].id);
      if(!left||!right||!left.node.isConnected||!right.node.isConnected||left.node.nextElementSibling!==right.node)continue;
      if(!left.raw.questionId||left.raw.questionId!==right.raw.questionId||Number(right.raw.sourcePageIndex||right.raw.page)<=Number(left.raw.sourcePageIndex||left.raw.page))continue;
      if(!/[\u3400-\u9fff]$/.test(left.text)||! /^[\u3400-\u9fff]/.test(right.text))continue;
      while(right.node.firstChild)left.node.append(right.node.firstChild);
      right.node.remove();right.node=left.node;joins++;
    }
    if(joins)root.dataset.pageFlowJoins=String(joins);
    if(/^\d+$/.test(number)){
      var first=body.querySelector('.question')||body.firstElementChild;
      if(first){var walker=document.createTreeWalker(first,NodeFilter.SHOW_TEXT),text;
        while((text=walker.nextNode())){if(!text.textContent.trim())continue;text.textContent=text.textContent.replace(new RegExp('^\\s*'+number+'\\s*[.．、]\\s*'),'');break;}}
    }
    root.dataset.choiceReady='true';
    if(reveal)reveal.addEventListener('click',function(e){
      e.preventDefault();e.stopPropagation();
      var adjacent=following(root);
      if(adjacent&&adjacent.matches('details.paper-answer')){adjacent.open=true;return;}
      try{if(window.parent!==window){var nativeFlip=window.parent.document.getElementById('study-flip');if(nativeFlip&&nativeFlip.getAttribute('aria-pressed')!=='true'){nativeFlip.click();return;}}}catch(error){}
      // AnkiMobile uses a native WKWebView tap bridge. The owner has verified
      // the front midCenter action is Show Answer on the target phone/iPad.
      // window.anki.showAnswer is an HTML renderer, not a scheduler command.
      if(window.anki&&window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.cb&&typeof window.webkit.messageHandlers.cb.postMessage==='function'){
        try{window.webkit.messageHandlers.cb.postMessage(JSON.stringify({scheme:'ankitap',msg:'midCenter'}));return;}
        catch(error){reveal.textContent='原生翻面调用失败，请反馈客户端版本';return;}
      }
      if(typeof window.pycmd==='function'){window.pycmd('ans');return;}
      if(typeof window.showAnswer==='function'){window.showAnswer();return;}
      // Never fake a native scheduler transition by revealing answer HTML on
      // the question side when a client does not expose a reveal command.
      reveal.textContent='请使用客户端的显示答案按钮';
    });
    var type=record.questionType,options=record.options||[];
    if((type!=='single_choice'&&type!=='multiple_choice')||!options.length)return;
    var nodes=Array.from(body.querySelectorAll('.choice'));
    // Image options already carry explicit source crops; never infer them.
    if(!nodes.length&&options.every(function(o){return o.image&&o.image.src===options[0].image.src&&o.image.crop;})){
      var figures=body.querySelectorAll('figure');
      if(figures.length===1&&figures[0].querySelectorAll('img').length===1){
        var crops=options.map(function(o){return o.image.crop;});
        if(crops.every(function(c){return ['x','y','width','height','sourceWidth','sourceHeight'].every(function(k){return Number.isFinite(c[k]);})&&c.x>=0&&c.y>=0&&c.width>0&&c.height>0&&c.x+c.width<=c.sourceWidth&&c.y+c.height<=c.sourceHeight;})){
          var choices=document.createElement('div');choices.className='choices exam-image-choices';
          options.forEach(function(o){var c=o.image.crop,row=document.createElement('div'),label=document.createElement('b'),view=document.createElement('span'),image=figures[0].querySelector('img').cloneNode();row.className='choice';label.textContent=o.label;view.className='exam-choice-image';view.style.cssText='display:block;position:relative;overflow:hidden;flex:0 1 auto;max-width:100%;width:'+(c.width*2)+'px;aspect-ratio:'+c.width+'/'+c.height;image.alt=o.image.alt||o.label;image.style.cssText='position:absolute;max-width:none;margin:0;height:auto;width:'+(100*c.sourceWidth/c.width)+'%;left:'+(-100*c.x/c.width)+'%;top:'+(-100*c.y/c.height)+'%';view.append(image);row.append(label,view);choices.append(row);});
          figures[0].hidden=true;figures[0].after(choices);nodes=Array.from(body.querySelectorAll('.choice'));
        }
      }
    }
    // Prove all option groups in document order before changing source DOM.
    if(nodes.length!==options.length){
      var parts=options.map(function(o){return clean((o.sourceLabel||o.label)+' '+o.text);});
      var paragraphs=Array.from(body.querySelectorAll('p,.choice')).filter(function(n){return !n.parentElement.closest('.choice');}),matched=[],cursor=0;
      paragraphs.forEach(function(p){
        if(cursor>=options.length)return;
        var text=p.textContent,flat='',positions=[];
        for(var i=0;i<text.length;i++){if(!/\s/.test(text[i])){flat+=text[i];positions.push(i);}}
        if(p.matches('.choice')&&flat===parts[cursor]){cursor++;return;}
        for(var stop=options.length;stop>cursor;stop--){
          var segment=parts.slice(cursor,stop).join('');
          if(!segment||!flat.endsWith(segment))continue;
          var first=flat.length-segment.length,prefix=flat.slice(0,first);
          if(cursor&&prefix&&!/^\d+[.．、]（续）$/.test(prefix))continue;
          var offsets=[],contentOffsets=[],at=first;
          for(var j=cursor;j<stop;j++){offsets.push(positions[at]);var length=clean(options[j].sourceLabel||options[j].label).length;contentOffsets.push(positions[at+length-1]+1);at+=parts[j].length;}
          matched.push({node:p,start:cursor,stop:stop,offsets:offsets,contentOffsets:contentOffsets,continuation:!!(cursor&&prefix)});cursor=stop;break;
        }
      });
      if(cursor===options.length){
        matched.forEach(function(m){
          var texts=[],walker=document.createTreeWalker(m.node,NodeFilter.SHOW_TEXT),node,total=0;
          while((node=walker.nextNode())){texts.push({node:node,start:total,end:total+node.textContent.length});total+=node.textContent.length;}
          var point=function(offset){var found=texts.find(function(t){return offset<t.end;});return found?[found.node,offset-found.start]:[m.node,m.node.childNodes.length];};
          var prefix=document.createRange();prefix.setStart(m.node,0);var initial=point(m.offsets[0]);prefix.setEnd(initial[0],initial[1]);
          var before=prefix.cloneContents(),group=document.createElement('div');group.className='choices';
          options.slice(m.start,m.stop).forEach(function(o,index){
            var range=document.createRange(),begin=point(m.contentOffsets[index]);range.setStart(begin[0],begin[1]);
            if(index+1<m.offsets.length){var end=point(m.offsets[index+1]);range.setEnd(end[0],end[1]);}else range.setEnd(m.node,m.node.childNodes.length);
            var row=document.createElement('div');row.className='choice';var label=document.createElement('b'),content=document.createElement('span');label.textContent=o.sourceLabel||o.label;content.append(range.cloneContents());row.append(label,content);group.append(row);
          });
          if(m.node.matches('.choice'))m.node.replaceWith.apply(m.node,Array.from(group.children));
          else if(m.continuation)m.node.replaceWith(group);
          else{m.node.replaceChildren(before);m.node.after(group);if(!m.node.textContent.trim()&&!m.node.querySelector('img,math'))m.node.remove();}
        });nodes=Array.from(body.querySelectorAll('.choice'));
      }
    }
    if(nodes.length!==options.length)return;
    var key='exam-choice-v1:'+heading.textContent.trim(),picked=[];
    // A newly rendered question starts unanswered. Retain the choice only
    // while rendering its answer side, not when another review begins.
    var answerSide=!!(next&&next.classList.contains('exam-answer'));
    try{if(answerSide)picked=JSON.parse(sessionStorage.getItem(key)||'[]');else sessionStorage.removeItem(key);}catch(e){}
    if(!Array.isArray(picked))picked=[];
    var multi=type==='multiple_choice',labels=options.map(function(o){return String(o.label).replace(/[^A-Za-z0-9]/g,'');});
    // Preserve a known source-label duplication visibly, while giving each
    // physical option a unique interaction identity. Raw fields stay intact.
    if(labels.join(',')==='A,B,B,D'){
      var originalLabels=labels.slice();labels=['A','B','C','D'];
      nodes.forEach(function(n,i){n.dataset.originalChoiceLabel=originalLabels[i];if(labels[i]!==originalLabels[i]){var b=n.querySelector('b');if(b)b.textContent=labels[i]+'.';n.title='原稿此项标为'+originalLabels[i]+'，按原选项顺序对应'+labels[i];}});
      var notice=document.createElement('p');notice.className='exam-source-notice';notice.textContent='来源提示：原稿选项标为 A、B、B、D；第3项按原顺序显示为 C，原始标记保留在来源记录中。';body.append(notice);
    }
    picked=picked.filter(function(v){return labels.indexOf(v)>=0;});if(!multi)picked=picked.slice(0,1);
    var correct=[],answer=source.answer;
    if(answer&&answer.status==='explicit'&&typeof answer.value==='string'&&/^[A-Z]+$/.test(answer.value.trim())){
      var candidate=Array.from(answer.value.trim());
      if(new Set(candidate).size===candidate.length&&candidate.every(function(v){return labels.indexOf(v)>=0;})&&(multi||candidate.length===1))correct=candidate;
    }
    var descriptions=nodes.map(function(n){return n.textContent.trim();});
    var paint=function(){
      var adjacent=following(root),shown=!!(adjacent&&(adjacent.classList.contains('exam-answer')&&adjacent.getAttribute('data-answer-status')==='available'||adjacent.matches('details.paper-answer')&&adjacent.open&&adjacent.querySelector('.exam-answer[data-answer-status="available"]')));
      nodes.forEach(function(n,i){
        var yes=picked.indexOf(labels[i])>=0,expected=correct.indexOf(labels[i])>=0,result='';
        n.classList.toggle('exam-choice-selected',yes);n.setAttribute('aria-checked',String(yes));
        n.classList.remove('exam-choice-wrong','exam-choice-right','exam-choice-missed');
        var badge=n.querySelector('.exam-choice-result');if(badge)badge.remove();
        if(shown&&correct.length){
          if(yes&&!expected){n.classList.add('exam-choice-wrong');result='选错';}
          else if(yes&&expected){n.classList.add('exam-choice-right');result='选对';}
          else if(expected){n.classList.add(picked.length?'exam-choice-missed':'exam-choice-right');result=picked.length?'漏选':'正确答案';}
        }
        n.setAttribute('aria-label',descriptions[i]+(result?'，'+result:''));
        if(result){badge=document.createElement('span');badge.className='exam-choice-result tappable';badge.setAttribute('aria-hidden','true');badge.textContent=result;n.append(badge);}
      });
      try{sessionStorage.setItem(key,JSON.stringify(picked));}catch(e){}
    };
    root._examChoicePaint=paint;
    if(next&&next.matches('details.paper-answer')){next.addEventListener('toggle',paint);root._examLinkedDetail=next;}
    var choose=function(i){var label=labels[i];if(multi){picked=picked.indexOf(label)>=0?picked.filter(function(v){return v!==label;}):picked.concat([label]);picked.sort(function(a,b){return labels.indexOf(a)-labels.indexOf(b);});}else{picked=picked[0]===label?[]:[label];}paint();};
    body.setAttribute('role',multi?'group':'radiogroup');body.setAttribute('aria-label',multi?'多选题选项':'单选题选项');
    nodes.forEach(function(n,i){n.classList.add('exam-choice-interactive','tappable');n.setAttribute('role',multi?'checkbox':'radio');n.tabIndex=0;
      n.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();choose(i);});
      n.addEventListener('keydown',function(e){if(e.key===' '||e.key==='Enter'){e.preventDefault();e.stopPropagation();choose(i);}else if(!multi&&['ArrowDown','ArrowRight','ArrowUp','ArrowLeft'].indexOf(e.key)>=0){e.preventDefault();e.stopPropagation();var next=(i+(e.key==='ArrowDown'||e.key==='ArrowRight'?1:nodes.length-1))%nodes.length;nodes[next].focus();picked=[labels[next]];paint();}});
    });paint();
  });
 }
 // FrontSide includes this script. During HTML parsing, wait until the answer
 // sibling exists before deciding whether this is a fresh question or a back.
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});else initialize();
})();</script>"""
from .study_exam_display import INITIALIZE as DISPLAY_INITIALIZE, CSS as DISPLAY_CSS
CHOICE_SCRIPT = CHOICE_SCRIPT.replace(' function initialize(){', ' function initialize(){' + DISPLAY_INITIALIZE, 1)

FRONT = '<div class="exam-location">{{Title}}</div><article class="exam-notecard"><span class="exam-identity" hidden>{{Title}}</span><div class="exam-body">{{Question}}</div><div class="exam-answer-action"><button class="exam-reveal" type="button">查看答案</button></div><pre class="exam-selection-source tex2jax_ignore" hidden>{{SourceRecord}}</pre></article>' + CHOICE_SCRIPT
BACK = '{{FrontSide}}<article id="answer" class="exam-notecard exam-answer" data-answer-status="{{Status}}"><span class="exam-identity" hidden>{{Title}}</span><header class="exam-answer-heading">答案与解析</header><div class="exam-body">{{Answer}}</div><footer class="exam-source">{{Source}}</footer><details class="exam-audit"><summary>来源与原始记录</summary><pre>{{SourceRecord}}</pre></details></article>' + CHOICE_SCRIPT

CSS = '''.card{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:18px;line-height:1.85;color:#243248;background:#f5f7fb;text-align:left;margin:0;padding:12px;overflow-wrap:break-word}.exam-notecard{box-sizing:border-box;max-width:920px;margin:14px auto 24px;padding:26px 30px;background:white;border:1px solid #dce5f1;border-radius:16px}.exam-heading{padding-bottom:15px;margin-bottom:18px;border-bottom:1px solid #e5ebf3}.exam-heading>span{font-size:13px;font-weight:600;color:#5374a5;letter-spacing:.04em}.exam-heading h1{font-size:20px;line-height:1.5;margin:8px 0 0}.exam-body p{margin:.8em 0}.exam-body h2,.exam-body h3{font-size:18px;margin:1.4em 0 .6em}.choices{display:grid;gap:10px;margin:18px 0}.choice{display:flex;gap:12px;padding:10px 14px;background:#f7f9fc;border:1px solid #e5ebf3;border-radius:8px}.choice>b{flex:none;color:#355b91}.choice>span{min-width:0}.exam-body img{display:block;max-width:100%;height:auto;margin:16px auto}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #dce5f1;padding:8px 12px;vertical-align:top}.exam-answer{border-top:3px solid #527bb5}.exam-missing,.exam-answer[data-answer-status=missing]{border-color:#d9b876}.exam-missing{padding:15px;background:#fff9e9;border:1px solid #e5cf9a;border-radius:8px;color:#805f24}.exam-source{font-size:13px;color:#718198;margin-top:24px;padding-top:14px;border-top:1px solid #e5ebf3}.exam-audit{font-size:12px;color:#718198;margin-top:16px}.exam-audit summary{cursor:pointer}.exam-audit pre{white-space:pre-wrap;word-break:break-word;max-height:440px;overflow:auto}.nightMode.card,.night_mode.card{background:#181d25;color:#e2e7ef}.nightMode .exam-notecard,.night_mode .exam-notecard{background:#232b36;border-color:#3d4a5c}.nightMode .choice,.night_mode .choice{background:#2b3544;border-color:#3d4a5c}@media(max-width:600px){.card{padding:8px;font-size:17px}.exam-notecard{padding:20px 18px;border-radius:12px}.exam-heading h1{font-size:18px}}'''
CSS += '.exam-selection-source[hidden]{display:none!important}.exam-choice-interactive{cursor:pointer;touch-action:manipulation;transition:border-color .12s,background-color .12s}.exam-choice-interactive:hover{border-color:#9bb9e5}.exam-choice-interactive:focus-visible{outline:3px solid #5c8ed3;outline-offset:2px}.exam-choice-selected{background:#e4edff!important;border-color:#386ec2!important;box-shadow:inset 3px 0 #386ec2}.exam-answer-action{display:flex;justify-content:flex-end;margin-top:20px}.exam-answer-action:has(.exam-reveal[hidden]){display:none}.exam-reveal{font:inherit;font-size:15px;font-weight:600;border:1px solid #245fc2;background:#245fc2;color:#fff;border-radius:8px;padding:9px 18px;cursor:pointer;touch-action:manipulation}.exam-reveal[hidden]{display:none!important}.nightMode .exam-choice-selected,.night_mode .exam-choice-selected{background:#263f64!important}'

CSS += '.exam-omitted-section,.exam-source,.exam-audit{display:none!important}'



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
    labels = question_type_labels(snapshot.get('question_type_labels'))
    decks = {}; missing = []; years = set(); groups = set()
    seen = set()
    for row in snapshot['questions']:
        if row['key'] in seen:
            raise ValueError('duplicate exam question identity')
        seen.add(row['key'])
        year = str(row['year']); years.add(year)
        if year not in decks:
            decks[year] = genanki.Deck(_number('exam-unit', book_id + ':' + year), title + '::' + year + ' 年')
        kind = labels.get(row['type'])
        if kind is None:raise ValueError('unsupported question type grouping')
        if row.get('type_label', kind) != kind:
            raise ValueError('question title and type label mapping differ')
        group = year + ':' + row['type']; groups.add(group)
        if group not in decks:
            decks[group] = genanki.Deck(_number('exam-unit', book_id + ':' + group), title + '::' + year + ' 年::' + kind)
        source = html.escape(row['source_label']) + '<br>题目 ID：' + html.escape(row['key'])
        record = dict(row['source_record'])
        if record.get('question_type_label', kind) != kind:
            raise ValueError('source record and type label mapping differ')
        if kind != question_type_labels()[row['type']]:
            record['question_type_label'] = kind
        fields = [html.escape(row['title']), row['question'], row['answer'], source, row['status'],
                  html.escape(json.dumps(record, ensure_ascii=False, separators=(',', ':')))]
        guid = genanki.guid_for('anki-pipeline/exam-question/v1', book_id, row['key'])
        note = genanki.Note(model=model, fields=fields, guid=guid,
                           tags=['exam', 'year::' + year, row['type'], 'answer::' + row['status']])
        decks[group].add_note(note)
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
    return {'book_id': book_id, 'notes': len(seen), 'cards': len(seen), 'years': len(years), 'groups': len(groups), 'media': len(resources),
            'missing_answer_suspended': len(missing), 'source_sha256': snapshot['source_sha256'],
            'package_sha256': package_sha256, 'bytes': destination.stat().st_size}

CSS += ' .exam-identity[hidden]{display:none!important}.exam-location{box-sizing:border-box;max-width:920px;margin:16px auto 8px;padding:0 4px;text-align:right;color:#718198;font-size:14px;line-height:1.6}.exam-answer-heading{font-size:16px;font-weight:600;color:#5374a5;margin-bottom:16px}.exam-location+.exam-notecard{margin-top:8px}'

CSS += '.exam-body{font-size:19px;line-height:1.8;font-weight:400}.exam-body .paragraph,.exam-body .choice,.exam-body .choice>span{font-size:inherit;font-family:inherit;line-height:inherit;font-weight:400}.exam-body .choice>b{font-size:1em;line-height:inherit;font-weight:500}.exam-body .choice{padding:8px 14px}.exam-body .question{margin-top:0;margin-bottom:18px}@media(max-width:600px){.exam-body{font-size:17px}}'

CSS += '.exam-body .choice>span:not(.exam-choice-result){flex:1}.exam-body .choice>.exam-choice-result{flex:none;align-self:center;margin-left:auto;font-size:13px;font-weight:500;line-height:1.5;white-space:nowrap}.exam-choice-wrong{background:#fff0f0!important;border-color:#d34b58!important;color:#a12635;box-shadow:inset 3px 0 #d34b58!important}.exam-choice-wrong>b{color:#a12635!important}.exam-choice-right{background:#edf9f1!important;border-color:#2a8b52!important;color:#1b6240;box-shadow:inset 3px 0 #2a8b52!important}.exam-choice-right>b{color:#1b6240!important}.exam-choice-missed{background:#fffae9!important;border-color:#c49a2d!important;border-style:dashed;color:#876314;box-shadow:inset 3px 0 #c49a2d!important}.exam-choice-missed>b{color:#876314!important}.nightMode .exam-choice-wrong,.night_mode .exam-choice-wrong{background:#4b2631!important;color:#ffcad0}.nightMode .exam-choice-right,.night_mode .exam-choice-right{background:#193d30!important;color:#bbefd0}.nightMode .exam-choice-missed,.night_mode .exam-choice-missed{background:#45391c!important;color:#f6dfa2}.nightMode .exam-choice-wrong>b,.night_mode .exam-choice-wrong>b,.nightMode .exam-choice-right>b,.night_mode .exam-choice-right>b,.nightMode .exam-choice-missed>b,.night_mode .exam-choice-missed>b{color:inherit!important}'

CSS += ".exam-body .code{white-space:pre;overflow-x:auto;max-width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;line-height:1.65;padding:12px 14px;border:1px solid #e5ebf3;background:#f7f9fc;border-radius:8px}.exam-body .code code{font:inherit}.exam-source-notice{font-size:13px!important;color:#8a651c;background:#fff8e7;border-left:3px solid #c49a2d;padding:10px 12px}.exam-body .math-display{max-width:100%;overflow-x:auto}"

CSS += '.exam-image-choices{grid-template-columns:repeat(2,minmax(0,1fr))}@media(max-width:500px){.exam-image-choices{grid-template-columns:1fr}}'

CSS += DISPLAY_CSS
