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
  report.body_question_numbers_remaining=await page.$$eval('.exam-notecard:not(.exam-answer)',roots=>roots.filter(r=>{const source=r.querySelector('.exam-selection-source');if(!source)return false;const q=JSON.parse(source.textContent).question;return new RegExp('^\\s*'+q.number+'[.．、]').test(r.querySelector('.exam-body').textContent);}).length);assert.equal(report.body_question_numbers_remaining,0);
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
  await show(single);
  assert.equal(await page.$eval('.exam-location',n=>n.textContent),`2023 ➫ 单选题 ➫ 第 ${single.number} 题`);
  assert.equal(await page.$$eval('.exam-pick-controls,.exam-pick-status,.exam-clear-choice',xs=>xs.length),0);
  await page.evaluate(()=>{window.__commands=[];window.pycmd=command=>window.__commands.push(command);});
  await page.click('.exam-choice-interactive:nth-child(1)');
  await page.click('.exam-choice-interactive:nth-child(1)');
  assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await page.click('.exam-choice-interactive:nth-child(1)');await page.click('.exam-choice-interactive:nth-child(2)');
  assert.deepEqual(await page.$$eval('[aria-checked="true"]',xs=>xs.map(x=>x.textContent.trim().slice(0,1))),['B']);
  await page.click('.exam-body .question');await page.click('body',{offset:{x:2,y:2}});
  assert.equal(await page.evaluate(()=>window.__commands.length),0);
  assert.equal(await page.$eval('body',e=>e.classList.contains('tappable')),true);
  await page.click('.exam-reveal');assert.deepEqual(await page.evaluate(()=>window.__commands),['ans']);
  await show(single,true);
  for(const selector of ['.exam-source','.exam-audit'])assert.equal(await page.$eval(selector,n=>getComputedStyle(n).display),'none');
  report.source_footer_and_audit_hidden=true;report.location_arrow_separator=true;
  assert.equal(await page.$$eval('.exam-question-reference',xs=>xs.length),0);
  assert.equal(await page.$eval('.exam-notecard',e=>e.nextElementSibling.classList.contains('exam-answer')),true);
  assert.equal(await page.$eval('.exam-reveal',e=>e.hidden),true);
  assert.equal(await page.$$eval('h1',xs=>xs.length),0);
  assert.equal(await page.$$eval('.exam-location',xs=>xs.length),1);
  assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  await page.click('.exam-choice-interactive:nth-child(2)');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await page.click('.exam-choice-interactive:nth-child(2)');
  await show(single);assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await page.focus('.exam-choice-interactive');await page.keyboard.press('Space');
  await page.keyboard.press('ArrowRight');assert.ok((await page.$eval('[aria-checked="true"]',e=>e.textContent)).startsWith('B'));
  await show(multi);await page.click('.exam-choice-interactive:nth-child(1)');await page.click('.exam-choice-interactive:nth-child(3)');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),2);
  await page.click('.exam-choice-interactive:nth-child(1)');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);
  await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true});await show(single);
  await page.tap('.exam-choice-interactive');await page.tap('.exam-choice-interactive');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  // Even a previous stored C for the next/revisited question must not leak
  // into a new front. Its subsequent answer also remains unselected.
  await show(single);await page.click('.exam-choice-interactive:nth-child(3)');await show(single,true);
  assert.equal(await page.$eval('[aria-checked="true"] b',n=>n.textContent[0]),'C');
  await page.evaluate(row=>{var d=new DOMParser().parseFromString(row.front,'text/html');sessionStorage.setItem('exam-choice-v1:'+d.querySelector('.exam-identity').textContent.trim(),JSON.stringify(['C']));},multi);
  await show(multi);assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await show(multi,true);assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  await show(single);assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),0);
  report.new_question_starts_unselected=true;report.next_answer_has_no_previous_choice=true;
  // Execute real FrontSide + back scripts in parser order, not only a fixture
  // with scripts removed. The first FrontSide script must not erase C.
  await show(single);await page.click('.exam-choice-interactive:nth-child(3)');
  const actualBack=single.back.replace(/(<article id="answer")/,fixture.script+'$1');
  await page.setContent('<style>'+fixture.css+'</style>'+actualBack+fixture.script);
  assert.equal(await page.$eval('[aria-checked="true"] b',n=>n.textContent[0]),'C');
  report.parser_order_frontside_retains_selection=true;
  report.single_replaces=true;report.single_deselects=true;report.multi_toggles=true;report.flip_retains_selection=true;report.keyboard=true;report.touch=true;report.only_explicit_reveal=true;report.status_controls_removed=true;report.front_above_answer=true;
  const graded=fixture.rows.find(r=>r.year===2021&&r.number==='17');
  await show(graded);await page.click('.exam-choice-interactive:nth-child(1)');await page.click('.exam-choice-interactive:nth-child(3)');
  assert.equal(await page.$$eval('.exam-choice-wrong,.exam-choice-right,.exam-choice-missed,.exam-choice-result',xs=>xs.length),0);
  await show(graded,true);
  assert.deepEqual(await page.$$eval('.choice',xs=>xs.map(n=>({label:n.querySelector('b').textContent[0],wrong:n.classList.contains('exam-choice-wrong'),right:n.classList.contains('exam-choice-right'),missed:n.classList.contains('exam-choice-missed')}))),[
    {label:'A',wrong:true,right:false,missed:false},{label:'B',wrong:false,right:false,missed:false},{label:'C',wrong:false,right:true,missed:false},{label:'D',wrong:false,right:false,missed:true}]);
  assert.equal(await page.$eval('.exam-choice-wrong',n=>getComputedStyle(n).backgroundColor),'rgb(255, 240, 240)');
  await page.click('.choice:nth-child(1)');await page.click('.choice:nth-child(4)');
  assert.equal(await page.$$eval('.exam-choice-wrong,.exam-choice-missed',xs=>xs.length),0);assert.equal(await page.$$eval('.exam-choice-right',xs=>xs.length),2);
  await show(graded);assert.equal(await page.$$eval('.exam-choice-result',xs=>xs.length),0);
  const unknownBase=fixture.rows.find(r=>r.year===2003&&r.number==='1');
  // Missing-answer rendering remains guarded after real sources become complete.
  const unanswered={...unknownBase,back:unknownBase.back.replaceAll('data-answer-status="available"','data-answer-status="missing"')};await show(unanswered);await page.click('.choice');await show(unanswered,true);assert.equal(await page.$$eval('.exam-choice-result',xs=>xs.length),0);
  const seam=fixture.rows.find(r=>r.year===2007&&r.number==='34');await show(seam);
  assert.ok((await page.$eval('.exam-body .question',n=>n.textContent)).includes('火气很重的文章'));
  assert.equal(await page.$$eval('.exam-body p',xs=>xs.length),3);report.cross_page_word_join=true;
  report.wrong_red=true;report.correct_green=true;report.missed_distinct=true;report.no_front_answer_leak=true;report.unknown_answers_not_graded=true;
  // Device-accepted AnkiMobile bridge must trigger native answer state, never
  // invoke the internal answer HTML renderer or interpret option/body taps.
  await page.evaluate(()=>{window.__mobileCommands=[];window.anki={showAnswer(){throw new Error('HTML renderer is not native reveal');}};window.webkit={messageHandlers:{cb:{postMessage(s){window.__mobileCommands.push(JSON.parse(s));}}}};});
  await show(single);await page.tap('.exam-choice-interactive');await page.tap('.exam-body .question');
  assert.deepEqual(await page.evaluate(()=>window.__mobileCommands),[]);
  await page.tap('.exam-reveal');assert.deepEqual(await page.evaluate(()=>window.__mobileCommands),[{scheme:'ankitap',msg:'midCenter'}]);
  await show(single,true);assert.equal(await page.$eval('.exam-reveal',n=>n.hidden),true);
  await page.evaluate(()=>{delete window.anki;delete window.webkit;});report.ankimobile_native_bridge=true;
  report.knowledge_restore_sections_omitted=0;
  for(const row of fixture.rows.filter(r=>r.back.includes('考点知识还原'))){
    await show(row,true);
    const omitted=await page.$$eval('.exam-answer .exam-body > .exam-omitted-section',xs=>xs.map(n=>({hidden:n.hidden,display:getComputedStyle(n).display,text:n.textContent})));
    assert.equal(omitted.length,2);assert.ok(omitted.every(n=>n.hidden&&n.display==='none'));assert.match(omitted[0].text,/考点知识还原/);assert.match(omitted[1].text,/见表/);
    assert.equal(await page.$eval('.exam-answer .exam-body h2:not(.exam-omitted-section)',n=>getComputedStyle(n).display==='none'),false);
    assert.equal(await page.$$eval('.exam-answer .exam-body h2',xs=>xs.filter(n=>n.textContent.includes('考点点拨')&&!n.hidden).length),1);
    report.knowledge_restore_sections_omitted++;
  }
  assert.equal(report.knowledge_restore_sections_omitted,29);
  // A denied storage API must not prevent choosing options.
  await page.evaluate(()=>{Object.defineProperty(window,'sessionStorage',{get(){throw new Error('denied');}});});await show(single);await page.click('.exam-choice-interactive');assert.equal(await page.$$eval('[aria-checked="true"]',xs=>xs.length),1);report.storage_denied=true;
  // A reused native page must recover its original gesture surface when the
  // next card is from another book, without a page reload.
  await page.evaluate(()=>{document.body.innerHTML='<p id="vocabulary">other book</p>';});
  await page.waitForFunction(()=>!window.__ankiExamSurfaceGuardV1);
  assert.equal(await page.$eval('body',e=>e.classList.contains('tappable')),false);
  assert.equal(await page.$eval('html',e=>e.classList.contains('tappable')),false);
  assert.equal(await page.$eval('body',e=>e.style.minHeight),'');
  report.other_book_lifecycle_restored=true;
 } finally {await browser.close();}
 fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1;});
