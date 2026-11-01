"""Shared display-only exam cleanup and offline code coloring.

Raw fields and source audit stay unchanged. Token spans preserve every code
character; answer cleanup only removes pure multi-question key summaries and
one explicit current-question prefix from the first explanation paragraph.
"""
import json
import re

# One source rule for the card surface and its Web catalog excerpt.
_SCORE_PREFIX = r'^(\s*(?:\d+\s*[.．、]\s*)?)[（(]\s*(?:(?:本题|本小题)\s*)?\d+(?:\.\d+)?\s*分\s*[）)]\s*'


def without_total_score(text):
    return re.sub(_SCORE_PREFIX, r'\1', text, count=1)


INITIALIZE = r"""
  var oldSizer=window.__ankiExamFigureSizerV1;if(oldSizer)oldSizer.cleanup();
  document.querySelectorAll('.exam-body figure img[data-exam-original-height]').forEach(function(img){img.style.width='100%';img.style.height='auto';});
  document.querySelectorAll('.exam-notecard:not(.exam-answer) .exam-body').forEach(function(body){
    var first=body.querySelector('.question')||body.firstElementChild;if(!first)return;
    var walk=document.createTreeWalker(first,NodeFilter.SHOW_TEXT),text;
    while((text=walk.nextNode())){if(!text.textContent.trim())continue;text.textContent=text.textContent.replace(new RegExp(__SCORE_PREFIX__), '$1');break;}
  });
  document.querySelectorAll('.exam-answer').forEach(function(answer){
    var body=answer.querySelector('.exam-body'),identity=answer.querySelector('.exam-identity');
    if(!body||!identity)return;
    body.querySelectorAll('p').forEach(function(p){
      var text=p.textContent.replace(/\s/g,'');
      if(/^(?:\d+[.．、][A-H](?:[,，、]?[A-H])*){2,}$/.test(text))p.remove();
    });
    body.querySelectorAll('table').forEach(function(table){
      var rows=Array.from(table.rows),values=[],valid=true,summaryHeader=false;
      rows.forEach(function(row){
        var cells=Array.from(row.cells).map(function(cell){return cell.textContent.replace(/\s/g,'');});
        if(cells.length&&cells.every(function(value,i){return value===(i%2?'答案':'题号');})){summaryHeader=true;return;}
        if(!cells.length||cells.length%2){valid=false;return;}
        for(var i=0;i<cells.length;i+=2){if(!/^\d+$/.test(cells[i])||!/^[A-H](?:[,，、]?[A-H])*$/.test(cells[i+1]))valid=false;values.push(cells[i]);}
      });
      if(summaryHeader&&valid&&values.length>=2&&new Set(values).size===values.length){var parent=table.parentElement;table.remove();if(parent.classList.contains('table-scroll')&&!parent.textContent.trim())parent.remove();}
    });
    var match=identity.textContent.match(/第\s*(\d+)\s*题/),first=body.querySelector('p');
    if(match&&first&&!first.dataset.examNumberRemoved){
      var walk=document.createTreeWalker(first,NodeFilter.SHOW_TEXT),text;
      while((text=walk.nextNode())){if(!text.textContent.trim())continue;text.textContent=text.textContent.replace(new RegExp('^\\s*'+match[1]+'\\s*[.．、]\\s*'),'');break;}
      first.dataset.examNumberRemoved='true';
    }
    body.querySelectorAll('p,h2,h3,h4').forEach(function(node){if(/^解析[：:]?$/.test(node.textContent.replace(/\s/g,'')))node.remove();});
  });
  document.querySelectorAll('.exam-body .code').forEach(function(block){
    if(block.dataset.examSyntax==='true')return;
    var target=block.querySelector('code')||block;
    // Do not flatten preexisting source markup, math or linked figures.
    if(target.children.length)return;
    var source=target.textContent,fragment=document.createDocumentFragment(),at=0;
    var tokens=/(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(^[ \t]*#[^\n]*)|\b(void|bool|boolean|char|short|int|long|float|double|unsigned|signed|size_t|struct|enum|typedef|const|static|volatile|auto|register)\b|\b(if|else|for|while|do|switch|case|default|break|continue|return|goto|sizeof|new|delete|true|false|NULL|TRUE|FALSE)\b|\b(0[xX][\da-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[uUlLfF]*)\b|\b([A-Za-z_]\w*)(?=\s*\()|([+*\/%=<>!&|^~?:-]+)/gm;
    var token,names=['comment','string','preprocessor','type','keyword','number','function','operator'];
    while((token=tokens.exec(source))){
      fragment.append(document.createTextNode(source.slice(at,token.index)));
      var span=document.createElement('span'),kind=token.slice(1).findIndex(function(value){return value!==undefined;});
      span.className='exam-syntax-'+names[kind];span.textContent=token[0];fragment.append(span);at=tokens.lastIndex;
    }
    fragment.append(document.createTextNode(source.slice(at)));
    if(fragment.textContent!==source)throw new Error('Exam code coloring changed source characters');
    target.replaceChildren(fragment);block.dataset.examSyntax='true';
  });
"""
INITIALIZE = INITIALIZE.replace('__SCORE_PREFIX__', json.dumps(_SCORE_PREFIX, ensure_ascii=False))
CSS = '''.exam-syntax-type,.exam-syntax-number{color:#0550c9}.exam-syntax-keyword,.exam-syntax-operator{color:#d1242f}.exam-syntax-function{color:#8250df}.exam-syntax-string{color:#0a3069}.exam-syntax-comment{color:#6e7781}.exam-syntax-preprocessor{color:#953800}.nightMode .exam-syntax-type,.nightMode .exam-syntax-number,.night_mode .exam-syntax-type,.night_mode .exam-syntax-number{color:#79c0ff}.nightMode .exam-syntax-keyword,.nightMode .exam-syntax-operator,.night_mode .exam-syntax-keyword,.night_mode .exam-syntax-operator{color:#ff7b72}.nightMode .exam-syntax-function,.night_mode .exam-syntax-function{color:#d2a8ff}.nightMode .exam-syntax-string,.night_mode .exam-syntax-string{color:#a5d6ff}.nightMode .exam-syntax-comment,.night_mode .exam-syntax-comment{color:#8b949e}'''

CSS += '.exam-body figure img[data-exam-original-height]{width:100%;height:auto;max-width:100%}'
