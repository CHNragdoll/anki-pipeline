/* Isolated QA clocks only: no selectors, geometry, timers, Promise observers or source text. */
let qaCompiledPhaseTaken=false;
function qaCompiledPhase(packet,index,sequenceValue,isCurrent){
 try{
  if(qaCompiledPhaseTaken||index!==1||packet.id!=='ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576'||!isCurrent())return null;
  qaCompiledPhaseTaken=true;
  const entry=compiledAssets.entries[packet.id],pins=new Map([[entry.html.sha256,'derived-html'],[entry.profile.sha256,'profile'],[compiledAssets.runtime.sha256,'runtime']]),assets=new Map();
  const points=new Set(['prepare-start','source-proofs-verified','compiled-assets-requested','compiled-assets-verified','compiled-recheck-verified','profile-json-parsed','profile-frozen','compiled-load-complete','derived-dom-parsed','authored-resources-ready','styles-ready','realm-ready','native-module-ready','registry-ready','body-adoption-start','body-connected','authors-complete','media-reset-complete','full-gate-start','full-gate-complete']);
  let sent=0,spanOrdinal=0;const seen=new Set();
  const now=()=>{try{const value=performance.now();return Number.isFinite(value)?value:null}catch(_){return null}};
  function send(row){try{if(sent>=64||!isCurrent())return;const at=now();if(at===null||!Number.isFinite(performance.timeOrigin))return;const value={type:'study-compiled-phase-clock',schema:'study-compiled-phase-clock.v1',id:packet.id,token:packet.token,sequence:sequenceValue,side:1,source:'shared-frame',timeOrigin:performance.timeOrigin,at,...row};parent.postMessage(value,'*');sent++}catch(_){}}
  function point(label){try{if(!points.has(label)||seen.has(label))return;seen.add(label);send({kind:'point',label})}catch(_){}}
  function span(label,start,pin){try{if(!['author-execute','batch-finally-refresh'].includes(label)||!Number.isFinite(start))return;const end=now();if(end===null||end<start)return;const row={kind:'span',label,ordinal:++spanOrdinal,start,end,elapsed:end-start};if(label==='author-execute'){if(!/^[a-f0-9]{64}$/.test(pin||''))return;row.pin=pin}send(row)}catch(_){}}
  function asset(pin,step,value){try{const resource=pins.get(pin);if(!resource||!['start','headers','text','verified','failed'].includes(step))return;if(step==='failed'){assets.delete(pin);return}let row=assets.get(pin);if(step==='start'){if(row)return;row={kind:'resource',label:'compiled-resource',resource,pin,request_start:now()};assets.set(pin,row);return}if(!row||row[step+'_at']!==undefined)return;row[step+'_at']=now();if(step==='headers')row.http_status=value;if(step==='text')row.text_utf16=value;if(step==='verified'){row.elapsed=row.verified_at-row.request_start;send({...row});assets.delete(pin)}}catch(_){}}
  const result=Object.freeze({now,point,span,asset});point('prepare-start');return result;
 }catch(_){return null}
}
