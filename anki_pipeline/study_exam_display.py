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
  var figureImages=function(){return Array.from(document.querySelectorAll('.exam-body img[data-exam-original-height]')).filter(function(img){return !img.closest('.choice')&&!img.closest('figure[hidden]');});};
  var sizeFigures=function(){figureImages().forEach(function(img){
    var ow=Number(img.dataset.examOriginalWidth),oh=Number(img.dataset.examOriginalHeight),nw=Number(img.dataset.examRedrawWidth),nh=Number(img.dataset.examRedrawHeight),parent=img.parentElement,available=parent&&parent.clientWidth;
    if(![ow,oh,nw,nh,available].every(function(v){return Number.isFinite(v)&&v>0;}))return;
    var targetHeight=oh*Math.min(1,available/ow),width=Math.min(available,targetHeight*nw/nh);
    var value=width.toFixed(4)+'px';if(img.style.width!==value)img.style.width=value;
    img.style.height='auto';img.style.maxWidth='100%';
  });};
  var observer=typeof ResizeObserver==='function'?new ResizeObserver(sizeFigures):null;
  var sizer={body:document.body,cleanup:function(){if(observer)observer.disconnect();window.removeEventListener('resize',sizeFigures);if(window.__ankiExamFigureSizerV1===sizer)delete window.__ankiExamFigureSizerV1;}};
  window.__ankiExamFigureSizerV1=sizer;window.addEventListener('resize',sizeFigures);
  if(observer)figureImages().forEach(function(img){observer.observe(img.parentElement);});sizeFigures();

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
    var match=identity.textContent.match(/第\s*(\d+)\s*题/),first=body.querySelector('p');
    if(match&&first&&!first.dataset.examNumberRemoved){
      var walk=document.createTreeWalker(first,NodeFilter.SHOW_TEXT),text;
      while((text=walk.nextNode())){if(!text.textContent.trim())continue;text.textContent=text.textContent.replace(new RegExp('^\\s*'+match[1]+'\\s*[.．、]\\s*'),'');break;}
      first.dataset.examNumberRemoved='true';
    }
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
