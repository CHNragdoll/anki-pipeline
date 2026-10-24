const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const original='/tmp/study-interval-train-pilot-v2-20261017-pqmsamlc';
const freeze=fs.readFileSync(original+'/FROZEN.json');
assert.equal(crypto.createHash('sha256').update(freeze).digest('hex'),'452246240a5a07c7aed23080472bb45dc0b70246b61de0e602bf8a8f5f784f2e');
const raw=fs.readFileSync(original+'/runtime.test.cjs','utf8');
const prelude=raw.slice(0,raw.indexOf("\ntest('new interval"));
const {fixture,profile,source}=new Function('require','__dirname',prelude+'\nreturn {fixture,profile,source};')(require('node:module').createRequire(original+'/runtime.test.cjs'),original);
const results=[];
for(const retained of [false,true]){
 const p=profile.paragraphs[0],i=p.segments.findIndex(s=>s.retained===retained);
 for(const after of ['none','mousedown','pointermove','pointerover']){
  const next=fixture({guardedLegacy:true}),old=fixture({html:source,legacy:true});
  try{
   for(const f of [old,next])f.dispatch(p.key,i,'click');
   const clicked={old:old.active().length,next:next.active().length};
   for(const f of [old,next])f.fire('keydown',f.d.body,{key:'Escape'});
   const escaped={old:old.active().length,next:next.active().length};
   assert.equal(escaped.old,0);assert.equal(escaped.next,0);
   if(after!=='none')for(const f of [old,next])f.dispatch(p.key,i,after,{pointerType:'mouse'});
   const ended={old:old.active().length,next:next.active().length};
   if(after==='none'||after==='mousedown')assert.deepEqual(ended,{old:0,next:0});
   if(after==='pointermove'){assert.equal(ended.old,0);assert(ended.next>0);}
   if(after==='pointerover'){assert(ended.old>0);assert(ended.next>0);}
   assert.equal(next.handle.stats().invalid,null);
   results.push({retained,sourceText:p.segments[i].text,sequence:['click','Escape',...(after==='none'?[]:[after])],clicked,escaped,ended,interval:next.handle.stats()});
  } finally {next.close();old.close();}
 }
}
console.log(JSON.stringify({schema:'study-interval-escape-review.v1',sourceFreezeSha256:'452246240a5a07c7aed23080472bb45dc0b70246b61de0e602bf8a8f5f784f2e',componentOnly:true,realBrowser:false,geometryMocked:true,pairedSequences:results.length,results},null,2));