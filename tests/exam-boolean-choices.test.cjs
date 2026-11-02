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
test('display cleanup hides source answer numbers and preserves formulas, code and records',()=>{
 const dom=new JSDOM('',{url:'https://local.test',runScripts:'outside-only'}),w=dom.window;
 w.document.body.innerHTML='<article class="exam-notecard exam-answer"><div class="exam-body"><div class="paragraph">九,</div><p>[答案] B,所以成立, 已知值 1,000.</p><p class="formula" data-tex="x,y">\\(x,y\\)</p><pre>a,b</pre></div><pre class="exam-selection-source" hidden>{"x":"a,b"}</pre></article>';
 w.eval(script);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
 assert.equal(w.document.querySelector('.paragraph'),null);
 assert.equal(w.document.querySelector('p').textContent,'【答案】 B, 所以成立, 已知值 1,000.');
 assert.equal(w.document.querySelector('.formula').textContent,'\\(x,y\\)');
 assert.equal(w.document.querySelector('.exam-body pre').textContent,'a,b');
 assert.equal(w.document.querySelector('.exam-selection-source').textContent,'{"x":"a,b"}');
 w.__ankiExamSurfaceGuardV1.cleanup();dom.window.close();
});
test('untypeset TeX, code strings and already typeset first paragraphs survive repeated initialization',()=>{
 const dom=new JSDOM('',{url:'https://local.test',runScripts:'outside-only'}),w=dom.window;
 w.document.body.innerHTML=String.raw`<article class="exam-notecard exam-answer"><div class="exam-body"><div class="paragraph"><mjx-container><mjx-math><mjx-c></mjx-c></mjx-math></mjx-container></div><p>[答案] B,成立 \(\text{[答案] a,b}\),然后.</p><div class="code">printf("a,b");</div></div></article>`;
 const raw=w.document.querySelector('p').textContent;
 w.eval(script);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));w.eval(script);
 assert(w.document.querySelector('.paragraph mjx-container'));
 assert(w.document.querySelector('p').textContent.includes(String.raw`\(\text{[答案] a,b}\)`));
 assert(w.document.querySelector('p').textContent.startsWith('【答案】 B, 成立'));
 assert.equal(w.document.querySelector('.code').textContent,'printf("a,b");');
 w.__ankiExamSurfaceGuardV1.cleanup();dom.window.close();
});
test('compound source heading is hidden and only comma and full stop are normalized',()=>{
 const dom=new JSDOM('',{url:'https://local.test',runScripts:'outside-only'}),w=dom.window;
 render(w,'复合题号','x',false,'fill_blank');
 const root=w.document.querySelector('.exam-notecard');delete root.dataset.choiceReady;
 root.querySelector('.exam-selection-source').textContent=JSON.stringify({question:{number:5,questionType:'fill_blank'}});
 root.querySelector('.exam-body').innerHTML='<p>一、(5)一实习生，条件：成立；“保留”（括号）。</p>';
 w.eval(script);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
 assert.equal(root.querySelector('.exam-body p').textContent,'一实习生, 条件：成立；“保留”（括号）.');
 w.__ankiExamSurfaceGuardV1.cleanup();dom.window.close();
});
