const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync('anki_pipeline/study_exam_package.py','utf8');
const script=source.match(/CHOICE_SCRIPT = r"""<script>([\s\S]*?)<\/script>"""/)[1];
function render(w,title,value,back=false,type='true_false'){
 const record={question:{number:1,questionType:type,options:[]},answer:{status:'explicit',value}};
 w.document.body.innerHTML=`<article class="exam-notecard"><span class="exam-identity" hidden>${title}</span><div class="exam-body"><p>判断命题</p></div><button class="exam-reveal">查看答案</button><pre class="exam-selection-source" hidden></pre></article>${back?'<article class="exam-notecard exam-answer" data-answer-status="available"></article>':''}`;
 w.document.querySelector('pre').textContent=JSON.stringify(record);
 w.eval(script);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
 return [...w.document.querySelectorAll('.choice')];
}
test('boolean options toggle, reveal grades, and a new question resets selection',()=>{
 const dom=new JSDOM('',{url:'https://local.test',runScripts:'outside-only'}),w=dom.window;
 let rows=render(w,'判断1','×');
 assert.deepEqual(rows.map(n=>n.textContent),['×','√']);
 rows[1].click();assert.equal(rows[1].getAttribute('aria-checked'),'true');
 assert.equal(w.document.querySelector('.exam-answer'),null);
 rows[1].click();assert.equal(rows[1].getAttribute('aria-checked'),'false');
 rows[1].click(); rows=render(w,'判断1','×',true);
 assert(rows[1].classList.contains('exam-choice-wrong'));
 assert(rows[0].classList.contains('exam-choice-missed'));
 rows=render(w,'判断2','√');assert(rows.every(n=>n.getAttribute('aria-checked')==='false'));
 rows[1].click();rows=render(w,'判断2','√',true);assert(rows[1].classList.contains('exam-choice-right'));
 rows=render(w,'判断2','√');assert(rows.every(n=>n.getAttribute('aria-checked')==='false'));
 w.__ankiExamSurfaceGuardV1.cleanup();dom.window.close();
});
test('unrecognized answer is never guessed and other question types remain unchanged',()=>{
 const dom=new JSDOM('',{url:'https://local.test',runScripts:'outside-only'}),w=dom.window;
 let rows=render(w,'未知','unknown',true);assert.equal(rows.length,2);assert(rows.every(n=>!n.className.includes('exam-choice-right')));
 assert.equal(render(w,'填空','×',false,'fill_blank').length,0);w.__ankiExamSurfaceGuardV1.cleanup();dom.window.close();
});
