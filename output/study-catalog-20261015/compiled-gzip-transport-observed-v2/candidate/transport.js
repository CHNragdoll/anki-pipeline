/* The three following transport functions are exact current HOST source. */
function makeCanonicalCompiledTextReader(fetch,safeURL,knownPinMatches,Response,TextDecoder,DecompressionStream,DOMException,transformRead){
function deliveryAborted(signal){if(signal?.aborted)throw signal.reason||new DOMException('Prepared card request was superseded','AbortError')}
async function deliveryText(response,signal,budget=null){if(budget===null)return response.text();const limited=()=>Object.assign(Error('Speculative card exceeds its streaming budget'),{name:'StudyPrefetchLimit'});if(!response.body?.getReader)throw limited();const reader=response.body.getReader(),decoder=new TextDecoder(),parts=[];let bytes=0,complete=false;try{for(;;){deliveryAborted(signal);const value=await reader.read();if(value.done){complete=true;break}bytes+=value.value.byteLength;if(bytes>budget)throw limited();parts.push(decoder.decode(value.value,{stream:true}))}return parts.join('')+decoder.decode()}finally{if(!complete)await reader.cancel().catch(()=>{});reader.releaseLock()}}
async function verifiedArtifactText(rule,signal,budget=null){deliveryAborted(signal);let text=null;if(rule.gzipSrc&&typeof DecompressionStream==='function'){try{const response=await fetch(safeURL(rule.gzipSrc),{signal});if(!response.ok)throw Error('Prepared artifact HTTP '+response.status);text=await deliveryText(response.headers.get('Content-Encoding')==='gzip'?response:new Response(response.body.pipeThrough(new DecompressionStream('gzip'))),signal,budget)}catch(error){deliveryAborted(signal);if(['AbortError','StudyPrefetchLimit'].includes(error.name))throw error;text=null}}deliveryAborted(signal);if(text===null){const response=await fetch(safeURL(rule.src),{signal});if(!response.ok)throw Error('Prepared artifact HTTP '+response.status);text=await deliveryText(response,signal,budget)}deliveryAborted(signal);if(!await knownPinMatches(text,rule.sha256))throw Error('Prepared artifact SHA differs');deliveryAborted(signal);return text}
const originalDeliveryText=deliveryText;
deliveryText=(response,signal,budget)=>transformRead(originalDeliveryText,response,signal,budget);
return verifiedArtifactText;
}
/* QA-only transport adaptation. No body, profile, execution or readiness change. */
function createCompiledArtifactTransport(assets,document,fetcher,matches,scope){
 'use strict';
 const records=new WeakMap(),pattern=/^_qa_compiled_[a-z0-9_]+\.(?:js|json|html)$/;
 function bad(){throw Error('Compiled transport descriptor differs')}
 function fields(value){
  if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype)bad();
  const keys=Reflect.ownKeys(value);if(keys.length!==3||keys.some(key=>!['src','sha256','gzipSrc'].includes(key)))bad();
  const result={};for(const key of keys){const d=Object.getOwnPropertyDescriptor(value,key);if(!d||!Object.prototype.hasOwnProperty.call(d,'value')||typeof d.value!=='string')bad();result[key]=d.value}
  if(!pattern.test(result.src)||!/^[a-f0-9]{64}$/.test(result.sha256)||result.gzipSrc!==result.src+'.gz')bad();
  const raw=new URL(result.src,document.baseURI),gzip=new URL(result.gzipSrc,document.baseURI),base=new URL(document.baseURI);
  if(raw.origin!==base.origin||gzip.origin!==base.origin||raw.username||raw.password||raw.search||raw.hash||gzip.search||gzip.hash||gzip.href!==raw.href+'.gz')bad();
  return Object.freeze({...result,url:raw.href,gzipURL:gzip.href});
 }
 function remember(rule){if(records.has(rule))return;records.set(rule,fields(rule))}
 remember(assets.runtime);for(const entry of Object.values(assets.entries)){remember(entry.html);remember(entry.profile)}
 function validate(rule,url,pin){const saved=records.get(rule);if(!saved)bad();const now=fields(rule);if(now.url!==url||now.sha256!==pin||Object.keys(saved).some(key=>saved[key]!==now[key]))bad();return saved}
 async function read(rule,url,pin,phase,signal,budget=null){
  const saved=validate(rule,url,pin),totals=new WeakMap();
  const request=async(value,options)=>{
   const target=String(value);if(target!==saved.url&&target!==saved.gzipURL)bad();
   const gzip=target===saved.gzipURL,response=await fetcher(target,gzip?options:{...options,headers:{Range:'bytes=0-'}});
   if(gzip&&response.status!==200)throw Error('Compiled gzip representation HTTP '+response.status);
   if(!gzip&&response.status===206){const range=/^bytes 0-(\d+)\/(\d+)$/i.exec(response.headers.get('Content-Range')||'');if(!range||!Number.isSafeInteger(Number(range[2]))||Number(range[2])<=0||Number(range[1])!==Number(range[2])-1)throw Error('Prepared resource range is not complete');totals.set(response,Number(range[2]))}
   phase?.asset(pin,'headers',response.status);return response;
  };
  const readTransform=async(original,response,activeSignal,activeBudget)=>{const text=await original(response,activeSignal,activeBudget),total=totals.get(response);if(total!==undefined&&new scope.TextEncoder().encode(text).byteLength!==total)throw Error('Prepared resource byte length differs from complete range');phase?.asset(pin,'text',text.length);return text};
  const safe=value=>{const target=new URL(value,document.baseURI).href;if(target!==saved.url&&target!==saved.gzipURL)bad();return target};
  const text=await makeCanonicalCompiledTextReader(request,safe,matches,scope.Response,scope.TextDecoder,scope.DecompressionStream,scope.DOMException,readTransform)(saved,signal,budget);
  validate(rule,url,pin);phase?.asset(pin,'verified');return text;
 }
 return Object.freeze({validate,read});
}
