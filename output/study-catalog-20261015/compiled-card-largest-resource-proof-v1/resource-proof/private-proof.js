// Proofs are keyed weakly by the original cache promise. No owner or extra cache.
const resourceProofs=new WeakMap();
function verifiedResourceString(reader,url,pin,text){
 try{
  if(reader!==resource||typeof url!=='string'||typeof pin!=='string'||!/^[a-f0-9]{64}$/.test(pin)||typeof text!=='string')return false;
  const task=scriptCache.get(url+'|'+pin),proof=task&&resourceProofs.get(task);
  return!!proof&&proof.pin===pin&&proof.text===text;
 }catch(_){return false}
}
