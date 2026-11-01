// Verify display-only cleanup and lossless syntax coloring in a browser.
const fs=require('node:fs'),assert=require('node:assert/strict'),puppeteer=require('puppeteer-core');
(async()=>{const f=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const report={questions:f.rows.length,answer_summaries_removed:0,explanation_prefixes_removed:0,code_blocks:0};
try{const page=await browser.newPage();await page.goto(process.env.EXAM_QA_ORIGIN||'http://127.0.0.1:8771/');
for(let start=0;start<f.rows.length;start+=50){const rows=f.rows.slice(start,start+50);await page.setContent('<style>'+f.css+'</style>'+rows.map(r=>r.back).join(''));
const before=await page.evaluate(()=>({codes:[...document.querySelectorAll('.exam-body .code')].map(n=>n.textContent),summaries:[...document.querySelectorAll('.exam-answer .exam-body p')].filter(p=>/^(?:\d+[.．、][A-H](?:[,，、]?[A-H])*){2,}$/.test(p.textContent.replace(/\s/g,''))).length,prefixes:[...document.querySelectorAll('.exam-answer')].filter(a=>{const n=a.querySelector('.exam-identity').textContent.match(/第\s*(\d+)\s*题/);const ps=[...a.querySelectorAll('.exam-body p')].filter(p=>!/^(?:\d+[.．、][A-H](?:[,，、]?[A-H])*){2,}$/.test(p.textContent.replace(/\s/g,'')));return n&&ps[0]&&new RegExp('^\\s*'+n[1]+'\\s*[.．、]').test(ps[0].textContent)}).length}));
await page.addScriptTag({content:f.script.replace(/^<script>/,'').replace(/<\/script>$/,'')});
const after=await page.evaluate(()=>({codes:[...document.querySelectorAll('.exam-body .code')].map(n=>n.textContent),summaries:[...document.querySelectorAll('.exam-answer .exam-body p')].filter(p=>/^(?:\d+[.．、][A-H](?:[,，、]?[A-H])*){2,}$/.test(p.textContent.replace(/\s/g,''))).length,prefixes:[...document.querySelectorAll('.exam-answer')].filter(a=>{const n=a.querySelector('.exam-identity').textContent.match(/第\s*(\d+)\s*题/),p=a.querySelector('.exam-body p');return n&&p&&new RegExp('^\\s*'+n[1]+'\\s*[.．、]').test(p.textContent)}).length,colored:document.querySelectorAll('.exam-syntax-type,.exam-syntax-keyword').length}));
assert.deepEqual(after.codes,before.codes,'all code characters and indentation must remain exact');assert.equal(after.summaries,0);assert.equal(after.prefixes,0);report.code_blocks+=before.codes.length;report.answer_summaries_removed+=before.summaries;report.explanation_prefixes_removed+=before.prefixes;
}
// Front score badges are display-only; ordinary formulas and subpart scores stay.
report.leading_total_scores_removed=0;
for(let start=0;start<f.rows.length;start+=60){
 const rows=f.rows.slice(start,start+60);await page.setContent('<style>'+f.css+'</style>'+rows.map(r=>r.front).join(''));
 const before=await page.$$eval('.exam-notecard:not(.exam-answer) .exam-body',ns=>ns.map(n=>n.textContent));
 const pattern=/^(\s*(?:\d+\s*[.．、]\s*)?)[（(]\s*(?:本题|本小题)?\s*\d+(?:\.\d+)?\s*分\s*[）)]\s*/;
 report.leading_total_scores_removed+=before.filter(t=>pattern.test(t)).length;
 await page.addScriptTag({content:f.script.replace(/^<script>/,'').replace(/<\/script>$/,'')});
 const after=await page.$$eval('.exam-notecard:not(.exam-answer) .exam-body',ns=>ns.map(n=>n.textContent));
 assert.equal(after.filter(t=>pattern.test(t)).length,0);
}
const sample=f.rows.find(r=>r.year===2012&&String(r.number)==='1');if(sample){await page.setContent('<style>'+f.css+'</style>'+sample.front+f.script);assert.equal(await page.$eval('.exam-syntax-type',n=>getComputedStyle(n).color),'rgb(5, 80, 201)');assert.equal(await page.$eval('.exam-syntax-keyword',n=>getComputedStyle(n).color),'rgb(209, 36, 47)');assert.equal(await page.$eval('.exam-syntax-function',n=>getComputedStyle(n).color),'rgb(130, 80, 223)');report.reference_code_colors=true;}
// A long non-summary is retained without pathological backtracking.
await page.setContent('<article class="exam-answer"><span class="exam-identity" hidden>test 第 999 题</span><div class="exam-body"><p>1. '+('A '.repeat(20000))+'</p></div></article>');
const started=Date.now();await page.addScriptTag({content:f.script.replace(/^<script>/,'').replace(/<\/script>$/,'')});
assert.equal(await page.$eval('.exam-answer p',n=>n.textContent.length),40003);report.long_non_summary_retained=true;report.long_non_summary_ms=Date.now()-started;
if(process.argv[4]){
 const math=f.rows.find(row=>row.front.includes('\\(')&&row.type==='single_choice');assert.ok(math);
 await page.setContent('<style>'+f.css+'</style>'+math.front+f.script);
 const before=await page.$eval('.exam-selection-source',n=>n.textContent);
 await page.addScriptTag({url:process.argv[4]});await page.evaluate(async()=>{await MathJax.startup.promise;});
 assert.equal((await page.$eval('.exam-selection-source',n=>n.textContent))===before,true,'math must not rewrite source metadata');
 assert.ok(await page.$eval('.exam-selection-source',n=>JSON.parse(n.textContent).question));
 assert.equal(await page.$$eval('.exam-choice-interactive',n=>n.length),math.options);report.metadata_survives_actual_math=true;
}
report.code_text_exact=true;fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2));console.log(report);
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
