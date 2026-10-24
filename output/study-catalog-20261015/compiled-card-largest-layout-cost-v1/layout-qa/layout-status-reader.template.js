 let layoutCostStatusRead=false,layoutCostStatusSnapshot=null;
 function readLayoutCostStatus(doc,token){
  if(layoutCostStatusRead)return layoutCostStatusSnapshot;
  layoutCostStatusRead=true;
  try{
   const descriptor=Object.getOwnPropertyDescriptor(frame.contentWindow,'StudyCompiledLayoutCostStatus'),api=descriptor&&'value'in descriptor?descriptor.value:null;
   const method=api&&Object.getOwnPropertyDescriptor(api,'read');
   if(!method||!('value'in method)||typeof method.value!=='function')return layoutCostStatusSnapshot={available:false,reason:'api-unavailable'};
   const value=method.value.call(api,doc);
   if(value===null)return layoutCostStatusSnapshot={available:false,reason:'no-current-sealed-snapshot'};
   if(!value||typeof value!=='object')return layoutCostStatusSnapshot={available:false,reason:'untrusted-status'};
   const spec=__LAYOUT_SPEC_LITERAL__,descriptors=Object.getOwnPropertyDescriptors(value),names=Object.keys(spec),snapshot={};
   if(Object.keys(descriptors).length!==names.length||!names.every(name=>descriptors[name]&&'value'in descriptors[name]))return layoutCostStatusSnapshot={available:false,reason:'untrusted-status'};
   for(const name of names){const field=spec[name],current=descriptors[name].value;if(current===null&&field.nullable){snapshot[name]=null;continue;}if(field.enum?!field.enum.includes(current):field.type==='integer'?!Number.isSafeInteger(current)||current<0:field.type==='number'?typeof current!=='number'||!Number.isFinite(current)||current<0:field.type==='boolean'?typeof current!=='boolean':true)return layoutCostStatusSnapshot={available:false,reason:'untrusted-status'};snapshot[name]=current;}
   if(snapshot.schema!=='study-compiled-layout-cost.v1'||snapshot.id!==CARD||snapshot.token!==token||!Number.isSafeInteger(snapshot.viewToken)||snapshot.viewToken<0)return layoutCostStatusSnapshot={available:false,reason:'untrusted-status'};
   return layoutCostStatusSnapshot={available:true,...snapshot};
  }catch(_){return layoutCostStatusSnapshot={available:false,reason:'status-read-failed'};}
 }
