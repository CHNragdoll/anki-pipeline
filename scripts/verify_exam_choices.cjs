// Browser acceptance for the shared authored exam template, using a read-only
// JSON fixture rendered from source questions. No catalog or study-state writes.
const fs = require('node:fs'), assert = require('node:assert/strict');
const puppeteer = require('puppeteer-core');
(async () => {
 const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
 const browser = await puppeteer.launch({executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless:true});
 const report = {questions:fixture.rows.length, choice_questions:0, options:0, errors:[]};
 try {
  const page = await browser.newPage(); await page.goto('http://127.0.0.1:8771/');
  await page.setContent('<style>'+fixture.css+'</style>'+fixture.rows.map(r=>r.front).join('')+fixture.script);
  const coverage = await page.$$eval('.exam-notecard', roots=>roots.map(r=>({ready:r.dataset.choiceReady==='true', options:r.querySelectorAll('.exam-choice-interactive').length})));
  fixture.rows.forEach((row,i)=>{
   if(row.type==='single_choice'||row.type==='multiple_choice') {
    assert.equal(coverage[i].ready,true,`${row.year} Q${row.number} not selectable`);
    assert.equal(coverage[i].options,row.options,`${row.year} Q${row.number} option coverage`);
    report.choice_questions++; report.options+=row.options;
   }else assert.equal(coverage[i].options,0);
  });
  async function show(row,back=false) {await page.setContent('<style>'+fixture.css+'</style>'+(back?row.back:row.front)+fixture.script);}
  const single=fixture.rows.find(r=>r.year===2023&&r.type==='single_choice');
  const multi=fixture.rows.find(r=>r.year===2023&&r.type==='multiple_choice');
  await show(single);await page.click('.exam-clear-choice').catch(()=>{});
  await page.click('.exam-choice-interactive:nth-child(1)');await page.click('.exam-choice-interactive:nth-child(2)');
  assert.deepEqual(await page.$$eval('[aria-checked="true"]',xs=>xs.map(x=>x.textContent.trim().slice(0,1))),['B']);
  await show(single,true);assert.ok((await page.$eval('.exam-pick-status',e=>e.textContent)).includes('B'));
  assert.equal(await page.$$eval('.exam-question-reference',xs=>xs.length),0);
  assert.equal(await page.$eval('.exam-notecard',e=>e.nextElementSibling.classList.contains('exam-answer')),true);
  assert.equal(await page.$$eval('h1',xs=>xs.length),0);
  assert.equal(await page.$$eval('.exam-location',xs=>xs.length),1);
  await page.click('.exam-choice-interactive:nth-child(1)');assert.ok((await page.$eval('.exam-pick-status',e=>e.textContent)).includes('A'));assert.equal(await page.$$eval('.exam-pick-status',xs=>xs.length),1);
  await page.click('.exam-clear-choice');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await page.click('.exam-choice-interactive:nth-child(2)');report.back_change_and_clear=true;report.front_above_answer=true;report.compact_top_right_path=true;
  await show(single);assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  await page.click('.exam-clear-choice');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await page.focus('.exam-choice-interactive');await page.keyboard.press('Space');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  await page.keyboard.press('ArrowRight');assert.ok((await page.$eval('[aria-checked="true"]',e=>e.textContent)).startsWith('B'));
  await show(multi);await page.click('.exam-choice-interactive:nth-child(1)');await page.click('.exam-choice-interactive:nth-child(3)');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),2);
  await page.click('.exam-choice-interactive:nth-child(1)');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true});await show(single);await page.tap('.exam-choice-interactive');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  report.single_replaces=true;report.multi_toggles=true;report.flip_retains_selection=true;report.keyboard=true;report.touch=true;
  // A denied storage API must not prevent choosing options.
  await page.evaluate(()=>{Object.defineProperty(window,'sessionStorage',{get(){throw new Error('denied');}});});await show(single);await page.click('.exam-choice-interactive');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);report.storage_denied=true;
 } finally {await browser.close();}
 fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});
