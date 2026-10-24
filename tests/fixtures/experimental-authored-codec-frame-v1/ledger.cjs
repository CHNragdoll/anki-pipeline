'use strict';
const crypto=require('node:crypto');
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
// This generation-only verifier consumes the exact original policy and bytes.
// Resource filenames carry no semantic authority. Unknown/partial ledgers never
// run the generation codec; their original byte string is returned unchanged.
function sourceCohort(doc,policy,resources){
 const pins=[];
 for(const script of doc.scripts){
  const type=(script.getAttribute('type')||'').trim().toLowerCase();
  if(['application/json','application/ld+json'].includes(type))continue;
  if(!['','text/javascript','application/javascript'].includes(type)||['async','defer','nomodule'].some(a=>script.hasAttribute(a)))return null;
  const src=script.getAttribute('src');let pin;
  if(src){pin=policy?.external?.[src];const raw=resources?.get(src);if(typeof pin!=='string'||typeof raw!=='string'||hash(raw)!==pin)return null}
  else{const rule=policy?.inline?.find(r=>r.source===script.textContent);if(!rule||hash(script.textContent)!==rule.sha256)return null;pin=rule.sha256}
  pins.push(pin);
 }
 return pins;
}
module.exports={sourceCohort,hash};
