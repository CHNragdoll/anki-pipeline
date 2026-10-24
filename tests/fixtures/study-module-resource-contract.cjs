'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),{createHash}=require('node:crypto');
const helper=JSON.parse(fs.readFileSync(0,'utf8'));
const hash=text=>createHash('sha256').update(text).digest('hex');
const text='真实模块🙂 localhost 保持原字节',pin=hash(text),bytes=Buffer.byteLength(text,'utf8');
const path='/book/evidence/_study_prepared_module_'+pin+'.js',absolute='http://example.test'+path;
const document={baseURI:'http://example.test/book/index.html'};
function fixture(options={}){
  const calls=[],cache=new Map();
  const fetch=async(url,settings={})=>{
    const headers=new Headers(settings.headers||{});
    calls.push({url,range:headers.get('Range'),method:settings.method||'GET'});
    const response=options.respond?options.respond(calls.length):options;
    return{ok:response.ok!==false,status:response.status||200,
      headers:new Headers(response.range?{'Content-Range':response.range}:{}),
      text:async()=>response.body===undefined?text:response.body};
  };
  const read=new Function('fetch','knownPinMatches','scriptCache','TextEncoder','document','URL',
    helper+';return resource;')(fetch,async(value,pin)=>hash(value)===pin,cache,TextEncoder,document,URL);
  return{read,calls,cache};
}
const passed=[],failed=[];
async function test(name,body){try{await body();passed.push(name)}catch(error){failed.push({name,message:error.message,stack:error.stack})}}
(async()=>{
  for(const url of [absolute,absolute+'?source=one&encoded=%2F',
    'evidence/_study_prepared_module_'+pin+'.js?source=relative',absolute+'#original-fragment']){
    await test('exact prepared module uses full GET: '+url,async()=>{
      const f=fixture();assert.equal(await f.read(url,pin),text);
      assert.deepEqual(f.calls,[{url,range:null,method:'GET'}]);
    });
  }
  const protectedPaths=[
    '/media/_study_'+pin+'.js',
    '/media/_as_runtime_'+pin.slice(0,24)+'.js',
    '/evidence/_study_prepared_module_'+pin.slice(0,24)+'.js',
    '/not-evidence/_study_prepared_module_'+pin+'.js',
    '/evidence-copy/_study_prepared_module_'+pin+'.js',
    '/evidence/nested/_study_prepared_module_'+pin+'.js',
    path+'/extra',
    '/evidence/_study_prepared_module_'+hash('different file')+'.js',
    '/media/original.js#'+path,
    '/media/original.js?source='+path,
    '/evidence%2F_study_prepared_module_'+pin+'.js',
    '/evidence/_study_prepared_module_'+pin+'.js.map',
  ];
  for(const url of protectedPaths)await test('legacy/unmatched pathname keeps Range: '+url,async()=>{
    const f=fixture();assert.equal(await f.read(url,pin),text);
    assert.deepEqual(f.calls,[{url,range:'bytes=0-',method:'GET'}]);
  });
  for(const invalidPin of [pin.toUpperCase(),'z'.repeat(64),pin.slice(0,24)]){
    await test('invalid/nonlowercase pin cannot enable GET: '+invalidPin,async()=>{
      const url='/evidence/_study_prepared_module_'+invalidPin+'.js',f=fixture();
      await assert.rejects(f.read(url,invalidPin),/SHA/);
      assert.equal(f.calls[0].range,'bytes=0-');
    });
  }
  for(const url of [absolute,'/media/legacy.js']){
    await test('complete 206 still verifies UTF8 bytes: '+url,async()=>{
      const f=fixture({status:206,range:'bytes 0-'+(bytes-1)+'/'+bytes});
      assert.equal(await f.read(url,pin),text);
    });
    const invalidRanges=[
      ['partial response','bytes 0-2/'+bytes,/complete|range/i],
      ['nonzero start','bytes 1-'+(bytes-1)+'/'+bytes,/complete|range/i],
      ['missing range',null,/range/i],
      ['unknown total','bytes 0-'+(bytes-1)+'/*',/range/i],
      ['unsafe total','bytes 0-9007199254740991/9007199254740992',/range/i],
      ['zero total','bytes 0-0/0',/range/i],
      ['wrong decoded byte count','bytes 0-'+bytes+'/'+(bytes+1),/byte|length/i],
      ['character count is not UTF8 byte count','bytes 0-'+(text.length-1)+'/'+text.length,/byte|length/i],
    ];
    for(const [name,range,reason]of invalidRanges)await test(name+' rejected even with correct body SHA: '+url,async()=>{
      const f=fixture({status:206,range});await assert.rejects(f.read(url,pin),reason);
    });
    await test('bad full 200 SHA remains rejected: '+url,async()=>{
      const f=fixture({body:text.replace('真实','篡改')});await assert.rejects(f.read(url,pin),/SHA/);
    });
    await test('complete 206 with same-length rewritten bytes remains rejected: '+url,async()=>{
      const f=fixture({status:206,range:'bytes 0-'+(bytes-1)+'/'+bytes,body:text.replace('真实','篡改')});
      await assert.rejects(f.read(url,pin),/SHA/);
    });
    await test('HTTP failure remains rejected: '+url,async()=>{
      const f=fixture({ok:false,status:404});await assert.rejects(f.read(url,pin),/HTTP 404/);
    });
  }
  await test('failed proof is removed from cache and can be retried',async()=>{
    const f=fixture({respond:attempt=>attempt===1?{body:'corrupted'}:{}});
    await assert.rejects(f.read(absolute,pin),/SHA/);assert.equal(f.cache.size,0);
    assert.equal(await f.read(absolute,pin),text);assert.equal(f.calls.length,2);
    assert.equal(await f.read(absolute,pin),text);assert.equal(f.calls.length,2);
  });
  await test('URL including query and pin remain the cache identity',async()=>{
    const f=fixture(),one=absolute+'?one',two=absolute+'?two';
    assert.deepEqual(await Promise.all([f.read(one,pin),f.read(one,pin)]),[text,text]);
    assert.equal(f.calls.length,1);assert.equal(await f.read(two,pin),text);assert.equal(f.calls.length,2);
    await assert.rejects(f.read(one,hash('other pin')),/SHA/);assert.equal(f.calls.length,3);
    assert.equal(await f.read(one,pin),text);assert.equal(f.calls.length,3);
  });
  await test('the existing 24-item cache bound and oldest eviction remain intact',async()=>{
    const f=fixture();for(let i=0;i<25;i++)await f.read(absolute+'?entry='+i,pin);
    assert.equal(f.cache.size,24);assert.equal(f.cache.has(absolute+'?entry=0|'+pin),false);
    await f.read(absolute+'?entry=0',pin);assert.equal(f.calls.length,26);assert.equal(f.cache.size,24);
  });
  console.log(JSON.stringify({pass:failed.length===0,contracts:passed.length+failed.length,passed,failed}));
  if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1});
