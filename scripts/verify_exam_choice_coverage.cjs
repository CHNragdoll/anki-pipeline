// Generic browser coverage for a read-only authored-exam fixture.
// rows: {front,back,type,options,year,number}; css/script from the shared model.
const fs=require('node:fs'),assert=require('node:assert/strict');
const puppeteer=require('puppeteer-core');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const report={questions:fixture.rows.length,choice_questions:0,options:0,failures:[]};
 try{
  const page=await browser.newPage();await page.goto(process.env.EXAM_QA_ORIGIN||'http://127.0.0.1:8771/');
  for(let start=0;start<fixture.rows.length;start+=60){
   const rows=fixture.rows.slice(start,start+60);
   await page.setContent('<style>'+fixture.css+'</style>'+rows.map(r=>r.front).join('')+fixture.script);
   const got=await page.$$eval('.exam-notecard',roots=>roots.map(root=>({ready:root.dataset.choiceReady==='true',options:root.querySelectorAll('.exam-choice-interactive').length,labels:[...root.querySelectorAll('.choice>b')].map(n=>n.textContent.replace(/[^A-Za-z0-9]/g,''))})));
   rows.forEach((row,index)=>{
    if(!['single_choice','multiple_choice'].includes(row.type))return;
    report.choice_questions++;report.options+=row.options;
    if(!got[index]?.ready||got[index].options!==row.options||new Set(got[index].labels).size!==row.options)report.failures.push({year:row.year,number:row.number,expected:row.options,actual:got[index]});
   });
  }
  assert.deepEqual(report.failures,[],'every source option needs one unique selectable control');
  // Inline formatting and a whitespace-separated label must survive splitting.
  const row=fixture.rows.find(r=>r.type==='single_choice');assert.ok(row);
  await page.setContent('<style>'+fixture.css+'</style>'+row.front+fixture.script);
  const sample=await page.$eval('.exam-notecard',root=>{
   const record=JSON.parse(root.querySelector('.exam-selection-source').textContent);record.question.number='999';record.question.options=[{label:'A.',text:'first'},{label:'B.',text:'f(x)&y'}];
   return '<article class="exam-notecard"><span class="exam-identity" hidden>whitespace fixture</span><div class="exam-body"><p>Stem. A . first B . <code>f(x)&amp;y</code></p></div><div class="exam-selection-source" hidden>'+JSON.stringify(record).replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</div></article>';
  });
  await page.setContent('<style>'+fixture.css+'</style>'+sample+fixture.script);
  assert.deepEqual(await page.$$eval('.choice',ns=>ns.map(n=>n.textContent.replace(/\s/g,''))),['A.first','B.f(x)&y']);
  assert.equal(await page.$eval('.choice code',n=>n.textContent),'f(x)&y');report.inline_markup_and_spaced_labels=true;
  console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1;});
