'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const document={baseURI:'https://study.example/book/index.html'};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}}
function script(attrs={},textContent=''){
  return{attrs:{...attrs},textContent,removed:0,
    getAttribute(name){return Object.hasOwn(this.attrs,name)?this.attrs[name]:null},
    hasAttribute(name){return Object.hasOwn(this.attrs,name)},
    set type(value){this.attrs.type=value},get type(){return this.attrs.type||''},
    remove(){this.removed++}};
}
function fixture(nodes,options={}){
  const calls=[],adapted=[],executed=[],cache=new Map();
  const packet={base:'https://study.example/book/media/',
    policy:{external:{'a.js':'a-original','native.js':'native-original','b.js':'b-original'},
      inline:[{source:'INLINE',sha256:'inline-original'}]},
    prepared:{modules:{'native-original':{src:'evidence/native-prepared.js',
      sha256:'native-prepared-pin',original_sha256:'native-original'}}}};
  if(options.edit)options.edit(packet);
  const resource=(url,pin)=>{
    const key=url+'|'+pin;if(cache.has(key))return cache.get(key);
    calls.push({url,pin});
    const value=options.read?options.read(url,pin):Promise.resolve(pin==='native-prepared-pin'?'MODULE':pin);
    cache.set(key,value);return value;
  };
  const adapt=(code,pin)=>{assert.notEqual(code,'MODULE','prepared module entered the ordinary author adapter');adapted.push({code,pin});return code};
  const collect=new Function('resource','adaptAuthoredCompactClassScan','URL','document',
    input.collector+';return collectAuthoredScripts;')(resource,adapt,URL,document);
  const active={modules:new Set()},win={__ankiCigenFrames:{batch:action=>action()}},doc={};
  const execute=(target,code,pin)=>{assert.equal(target,doc);executed.push({code,pin})};
  const runModules=new Function('scripts','packet','active','resource','URL','document',
    'valid','execute','doc','adaptNativeProjectionLookup',
    'return(async()=>{'+input.moduleLoop+';return true})()');
  const runAuthors=new Function('scripts','packet','win','valid','execute','doc',
    input.authorLoop+';return authoredComplete;');
  return{packet,calls,adapted,executed,collect:()=>collect({scripts:nodes},packet),
    modules:scripts=>runModules(scripts,packet,active,resource,URL,document,
      ()=>true,execute,doc,(code,pin)=>{assert.equal(pin,'native-original');return code}),
    authors:scripts=>runAuthors(scripts,packet,win,()=>true,execute,doc)};
}
function normalNodes(){return[script({src:'a.js'}),script({src:'native.js'}),
  script({src:'b.js'}),script({},'INLINE'),script({type:'application/json',src:'ignored.json'},'{}')]}
const nativeURL=new URL('evidence/native-prepared.js',document.baseURI).href;
const passed=[],failed=[];
async function test(name,body){try{await body();passed.push(name)}catch(error){failed.push({name,message:error.message,stack:error.stack})}}
(async()=>{
  await test('native read starts while both ordinary reads are still pending',async()=>{
    const a=deferred(),b=deferred(),native=deferred();
    const f=fixture(normalNodes(),{read:(url,pin)=>pin==='a-original'?a.promise:
      pin==='b-original'?b.promise:native.promise});
    const job=f.collect();job.catch(()=>{});let complete=false;job.then(()=>{complete=true},()=>{});
    try{
      assert.ok(f.calls.some(row=>row.url===nativeURL&&row.pin==='native-prepared-pin'),
        'prepared native module was not requested before ordinary scripts completed');
      assert.equal(f.calls.length,3);
      assert.equal(complete,false);
      a.resolve('A');b.resolve('B');await tick();
      assert.equal(complete,false,'collector did not await its verified module read');
      native.resolve('MODULE');const scripts=await job;
      assert.deepEqual(scripts.map(item=>item.pin),['a-original','native-original','b-original','inline-original']);
      assert.equal(scripts[1].code,null,'prepared module became an ordinary authored script');
      assert.ok(scripts.every(item=>item.node.type==='application/x-study-inert'));
      assert.deepEqual(f.adapted.map(item=>item.pin).sort(),['a-original','b-original','inline-original']);
      assert.equal(f.executed.length,0,'prefetch executed a module');
      await f.modules(scripts);await f.modules(scripts);
      assert.deepEqual(f.executed,[{code:'MODULE',pin:'native-original-prepared-native-prepared-pin'}]);
      assert.equal(f.calls.length,3,'the original module execution position did not reuse the resource promise');
      assert.equal(f.authors(scripts),true);
      assert.deepEqual(f.executed.slice(1),[
        {code:'A',pin:'a-original'},{code:'B',pin:'b-original'},{code:'INLINE',pin:'inline-original'}]);
      assert.equal(scripts[1].node.removed,1,'original native tag was not handled by its existing execution branch');
      assert.equal(f.calls.some(row=>row.url.endsWith('/media/native.js')),false);
    }finally{a.resolve('A');b.resolve('B');native.resolve('MODULE');await job.catch(()=>{})}
  });
  const invalid=[
    ['unknown external',()=>script({src:'unknown.js'}),null,/Unknown prepared script/],
    ['unknown inline',()=>script({},'UNKNOWN'),null,/Unknown prepared inline script/],
    ['module type',()=>script({src:'b.js',type:'module'}),null,/execution mode/],
    ['unknown type',()=>script({src:'b.js',type:'text/not-javascript'}),null,/execution mode/],
    ...['async','defer','nomodule'].flatMap(name=>[
      ['ordinary '+name,()=>script({src:'b.js',[name]:''}),null,/execution mode/],
      ['native '+name,()=>script({src:'native.js',[name]:''}),null,/execution mode/]]),
    ['wrong original native pin',()=>script({src:'b.js'}),
      packet=>{packet.prepared.modules['native-original'].original_sha256='wrong-original'},/module source SHA/],
  ];
  for(const [name,node,edit,reason]of invalid){
    await test('all policy validation precedes reads: '+name,async()=>{
      const f=fixture([script({src:'a.js'}),script({src:'native.js'}),node()],{edit});
      await assert.rejects(f.collect(),reason);assert.deepEqual(f.calls,[]);
      assert.equal(f.executed.length,0);
    });
  }
  await test('prepared descriptor supplies the module URL and verification pin',async()=>{
    const f=fixture([script({src:'native.js'})]);const scripts=await f.collect();
    assert.deepEqual(f.calls,[{url:nativeURL,pin:'native-prepared-pin'}]);
    assert.equal(scripts[0].code,null);assert.deepEqual(f.adapted,[]);assert.deepEqual(f.executed,[]);
  });
  await test('module verification rejection propagates without executing or adapting it',async()=>{
    const failure=Error('exact prepared module SHA rejection');
    const f=fixture(normalNodes(),{read:(url,pin)=>pin==='native-prepared-pin'?Promise.reject(failure):Promise.resolve(pin)});
    await assert.rejects(f.collect(),error=>error===failure);
    assert.equal(f.adapted.some(row=>row.pin==='native-original'),false);assert.deepEqual(f.executed,[]);
  });
  await test('ordinary rejection still propagates with concurrent native preparation',async()=>{
    const failure=Error('ordinary verified source rejection');
    const f=fixture(normalNodes(),{read:(url,pin)=>pin==='a-original'?Promise.reject(failure):Promise.resolve(pin==='native-prepared-pin'?'MODULE':pin)});
    await assert.rejects(f.collect(),error=>error===failure);assert.deepEqual(f.executed,[]);
    assert.ok(f.calls.some(row=>row.url===nativeURL));
  });
  await test('concurrent failures are handled even after the first read rejects',async()=>{
    const native=deferred(),ordinary=deferred(),unhandled=[],listener=error=>unhandled.push(error);
    process.on('unhandledRejection',listener);
    try{
      const f=fixture(normalNodes(),{read:(url,pin)=>pin==='native-prepared-pin'?native.promise:
        pin==='a-original'?ordinary.promise:Promise.resolve(pin)});
      const job=f.collect();const first=Error('ordinary first'),second=Error('module later');
      const rejected=assert.rejects(job,error=>error===first);ordinary.reject(first);await rejected;
      assert.ok(f.calls.some(row=>row.url===nativeURL));native.reject(second);await tick();await tick();
      assert.deepEqual(unhandled,[]);
    }finally{process.removeListener('unhandledRejection',listener);native.resolve('MODULE');ordinary.resolve('A')}
  });
  console.log(JSON.stringify({pass:failed.length===0,passed,failed}));
  if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1});
