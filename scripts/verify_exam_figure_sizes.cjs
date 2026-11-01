// Verify every declared redraw at desktop/mobile widths and after live resize.
const fs=require('node:fs'),assert=require('node:assert/strict'),puppeteer=require('puppeteer-core');
(async()=>{
 const snapshot=JSON.parse(fs.readFileSync(process.argv[2])),fixture=JSON.parse(fs.readFileSync(process.argv[3])),base=process.argv[4];
 const images=Object.entries(snapshot.resources).filter(([alias,r])=>r.recovery?.derivative).map(([alias,r])=>({alias,...r.recovery.derivative}));
 const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const report={images:images.length,viewports:[]};try{
  const page=await browser.newPage();await page.setViewport({width:1440,height:1000});await page.goto(base);
  const html=images.map(({alias,original_dimensions:o,replacement_dimensions:n})=>{assert.ok(o&&n);return '<figure><img src="'+base+'media/'+alias+'" data-exam-original-width="'+o.width+'" data-exam-original-height="'+o.height+'" data-exam-redraw-width="'+n.width+'" data-exam-redraw-height="'+n.height+'"><figcaption>图注</figcaption></figure>';}).join('');
  await page.setContent('<style>'+fixture.css+'</style><article class="exam-notecard"><div class="exam-body">'+html+'</div></article>'+fixture.script);
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  for(const width of [1440,390,1440]){
   await page.setViewport({width,height:1000});
   await page.waitForFunction(()=>[...document.images].every(i=>{let r=i.getBoundingClientRect(),a=i.parentElement.clientWidth;return Math.abs(r.width-a)<1;}));
   const values=await page.$$eval('img',ns=>ns.map(i=>{let r=i.getBoundingClientRect(),n=Number(i.dataset.examRedrawWidth)/Number(i.dataset.examRedrawHeight);return {ratioError:Math.abs(r.width/r.height-n),width:r.width,parent:i.parentElement.clientWidth,caption:getComputedStyle(i.parentElement.querySelector('figcaption')).textAlign};}));
   values.forEach(v=>{assert.ok(v.ratioError<0.015);assert.ok(Math.abs(v.width-v.parent)<1);assert.equal(v.caption,'center');});report.viewports.push({width,checked:values.length});
  }
  report.fill_available_width=true;report.aspect_ratio_locked=true;report.resize_recalculates=true;report.captions_centered=true;
  fs.writeFileSync(process.argv[5],JSON.stringify(report,null,2));console.log(report);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
