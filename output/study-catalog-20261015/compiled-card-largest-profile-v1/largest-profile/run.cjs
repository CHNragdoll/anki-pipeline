"use strict";
const fs=require("node:fs"),path=require("node:path"),crypto=require("node:crypto"),api=require("./ast-profile-css1.cjs"),{assemble}=require("./assemble-profile.cjs");
const D=__dirname,started=process.hrtime.bigint(),inputs={html:{path:"/tmp/study-largest-delivery-anchors-20261017-coh1q32d/replay-input-derived-anchored.html",sha256:"61118e38075f73091456ad2964c52e0393b5abdfa89989a417165f12cebfbbe3"},draft:{path:"/tmp/study-canonical-largest-pure-2026-20261017-x9d7jb4f/output/runtime-bindings-minimal-draft.json",sha256:"554d4b5025b8c546797fc372593f57a106744f58ae947ab67bb361dbb50570ea"}};
function save(extra){const value={schema:"study-largest-ast-extraction-report.v1",inputs,extractorSha256:api.sha(fs.readFileSync(path.join(D,"ast-profile-css1.cjs"))),elapsedMs:Number(process.hrtime.bigint()-started)/1e6,memory:{rss:process.memoryUsage().rss,maxRSSKiB:process.resourceUsage().maxRSS},...extra};fs.writeFileSync(path.join(D,"result.json"),JSON.stringify(value,null,2)+"\n");console.log(JSON.stringify(value));return value;}
(async()=>{try{
 let html=api.readPinnedUTF8(inputs.html.path,inputs.html.sha256,api.LIMITS.htmlBytes),draftRaw=api.readPinnedUTF8(inputs.draft.path,inputs.draft.sha256,api.LIMITS.draftBytes),draft=JSON.parse(draftRaw);
 const bindings=JSON.parse(fs.readFileSync(path.join(D,"reviewed-header-before-payload.json"),"utf8"));
 console.log(JSON.stringify({phase:"pins-verified",htmlBytes:Buffer.byteLength(html),draftBytes:Buffer.byteLength(draftRaw),pid:process.pid}));
 let result=api.projectFields({html,draft});
 if(result.index.manifests.length!==0)throw Error("slotless largest has a live manifest");if(result.index.reports.length!==8||result.index.examples.length!==1)throw Error("expected all eight live SF regions and one examples region");
 const payloads=result.index.payloads.map(p=>({rawSideSha256:api.get(p,"data-as-sha"),rawIndexSha256:api.get(p,"data-as-index-sha")}));
 const registry=[bindings.registrySha256_0,bindings.registrySha256_1];if(payloads.length!==1||!registry.includes(payloads[0].rawSideSha256)||!registry.includes(payloads[0].rawIndexSha256)||payloads[0].rawSideSha256===payloads[0].rawIndexSha256)throw Error("raw/index active payload source pins");
 Object.assign(bindings,payloads[0]);fs.writeFileSync(path.join(D,"bindings.json"),JSON.stringify(bindings,null,2)+"\n");
 const tables=Object.fromEntries(Object.entries(result.fields).map(([name,value])=>[name,Array.isArray(value)?value.length:value]));
 const diagnostics={...result.diagnostics,sfRegions:result.index.reports.length,examplesRegions:result.index.examples.length,documentMode:result.index.doc.mode};
 console.log(JSON.stringify({phase:"fields-ready",diagnostics,tables}));
 const fieldsFile=path.join(D,"fields.json"),fd=fs.openSync(fieldsFile,"wx"),hash=crypto.createHash("sha256");let bytes=0;
 function write(raw){const buffer=Buffer.from(raw);if(bytes+buffer.length>api.LIMITS.profileBytes)throw Error("field stream byte limit");let offset=0;while(offset<buffer.length){const n=fs.writeSync(fd,buffer,offset,buffer.length-offset);if(n<=0)throw Error("short field stream write");offset+=n}bytes+=buffer.length;hash.update(buffer)}
 try{write("{");let first=true;for(const[name,value]of Object.entries(result.fields)){if(!first)write(",");first=false;write(JSON.stringify(name)+":");if(Array.isArray(value)){write("[");for(let i=0;i<value.length;i++){if(i)write(",");write(JSON.stringify(value[i]))}write("]")}else write(JSON.stringify(value))}write("}")}finally{fs.closeSync(fd)}
 const extraction=save({status:"FIELDS_EXTRACTED_NOT_PROFILE",diagnostics,tables,payloads,draftSourceArtifactSha256:draft.source_artifact_sha256,fields:{path:fieldsFile,bytes,sha256:hash.digest("hex")}});
 result=null;html=null;draftRaw=null;draft=null;
 const assembled=await assemble({fieldsFile,fieldsSha256:extraction.fields.sha256,bindings,extraction},path.join(D,"profile"));
 save({...extraction,status:"PROFILE_ASSEMBLED_NOT_BROWSER_ACCEPTED",assembled});
}catch(error){save({status:"FAILED",error:error.stack||String(error),code:error.code||null,keyInsertions:error.keyInsertions||[]});process.exitCode=1}})();
