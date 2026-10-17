"use strict";
function normalizeAttributes(value){
 if(Array.isArray(value)){
  const names=new Set();for(const pair of value){if(!Array.isArray(pair)||pair.length!==2||typeof pair[0]!=="string"||!pair[0]||typeof pair[1]!=="string"||names.has(pair[0]))throw Error("Invalid/duplicate Bank attribute pair");names.add(pair[0]);}
  return Object.fromEntries(value);
 }
 if(!value||typeof value!=="object"||Object.getPrototypeOf(value)!==Object.prototype||Object.entries(value).some(([name,text])=>!name||typeof text!=="string"))throw Error("Invalid Bank attribute object");
 return value;
}
function canonicalBankRecords(records,nodeBindings){
 if(!Array.isArray(records)||!Array.isArray(nodeBindings))throw Error("Bank records/bindings shape");
 const nodes=new Map(nodeBindings.map(node=>[node.key,node]));
 return records.map(entry=>{
  const label=nodes.get(entry.labelKey);if(!label||!Array.isArray(label.requiredAttrs))throw Error("Missing Bank label binding");
  const source=new Map(label.requiredAttrs),normalized=normalizeAttributes(entry.compiledAttributes);
  if(Object.entries(normalized).some(([name,value])=>!source.has(name)||source.get(name)!==value)||typeof entry.evidence!=="string"||source.get("data-shared-reading-bank-evidence")!==entry.evidence||normalized["data-shared-reading-bank-evidence"]!==entry.evidence)throw Error("Bank attributes/evidence differ from bound source label");
  return normalized===entry.compiledAttributes?entry:{...entry,compiledAttributes:normalized};
 });
}
module.exports={normalizeAttributes,canonicalBankRecords};
