 let initialClaimStatusRead=false,initialClaimStatusSnapshot=null;
 function readInitialClaimStatus(doc,token){
  if(initialClaimStatusRead)return initialClaimStatusSnapshot;
  initialClaimStatusRead=true;
  try{
   const descriptor=Object.getOwnPropertyDescriptor(frame.contentWindow,'StudyCompiledInitialNumberingStatus'),api=descriptor&&'value'in descriptor?descriptor.value:null;
   const method=api&&Object.getOwnPropertyDescriptor(api,'read');
   if(!method||!('value'in method)||typeof method.value!=='function')return initialClaimStatusSnapshot={available:false,reason:'api-unavailable'};
   const value=method.value.call(api,doc);
   if(value===null)return initialClaimStatusSnapshot={available:false,reason:'no-current-snapshot'};
   if(!value||typeof value!=='object')return initialClaimStatusSnapshot={available:false,reason:'untrusted-status'};
   const names=['schema','id','token','viewToken','qualified','readerCaptured','attempted','accepted','rows','reason'],descriptors=Object.getOwnPropertyDescriptors(value),snapshot={};
   if(Object.keys(descriptors).length!==names.length||!names.every(name=>descriptors[name]&&'value'in descriptors[name]))return initialClaimStatusSnapshot={available:false,reason:'untrusted-status'};
   for(const name of names)snapshot[name]=descriptors[name].value;
   if(snapshot.schema!=='study-compiled-initial-numbering-status.v1'||snapshot.id!==CARD||snapshot.token!==token||!Number.isSafeInteger(snapshot.viewToken)||snapshot.viewToken<0||!['qualified','readerCaptured','attempted','accepted'].every(name=>typeof snapshot[name]==='boolean')||!Number.isSafeInteger(snapshot.rows)||snapshot.rows<0||snapshot.rows>8192||!["not-consumed","reader-capture-mismatch","accepted","claim-mismatch","unqualified-input"].includes(snapshot.reason))return initialClaimStatusSnapshot={available:false,reason:'untrusted-status'};
   return initialClaimStatusSnapshot={available:true,...snapshot};
  }catch(_){return initialClaimStatusSnapshot={available:false,reason:'status-read-failed'};}
 }
