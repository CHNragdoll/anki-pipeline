 let phase_generation=null,phase_time_origin=null;
 const phase_clock=[],phasePointLabels=new Set(['prepare-start','source-proofs-verified','compiled-assets-requested','compiled-assets-verified','compiled-recheck-verified','profile-json-parsed','profile-frozen','compiled-load-complete','derived-dom-parsed','authored-resources-ready','styles-ready','realm-ready','native-module-ready','registry-ready','body-adoption-start','body-connected','authors-complete','media-reset-complete','full-gate-start','full-gate-complete']);
 const ownKeysExactly=(value,names)=>Object.keys(value).length===names.length&&names.every(name=>Object.prototype.hasOwnProperty.call(value,name));
 const phaseNumber=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
 function receivePhase(data){
  if(accepted===null||data.token!==accepted||data.schema!=='study-compiled-phase-clock.v1'||data.side!==1||data.source!=='shared-frame'||frame.dataset.mountMode!=='shared'||phase_clock.length>=64||!Number.isSafeInteger(data.sequence)||data.sequence<0||phase_generation!==null&&data.sequence!==phase_generation||!phaseNumber(data.timeOrigin)||phase_time_origin!==null&&data.timeOrigin!==phase_time_origin||!phaseNumber(data.at))return;
  const names=['type','schema','id','token','sequence','side','source','timeOrigin','at','kind','label'],row={schema:data.schema,id:data.id,token:data.token,sequence:data.sequence,side:1,source:'shared-frame',timeOrigin:data.timeOrigin,at:data.at,kind:data.kind,label:data.label};
  if(data.kind==='point'){
   if(!phasePointLabels.has(data.label)||!ownKeysExactly(data,names))return;
  }else if(data.kind==='span'){
   if(!['author-execute','batch-finally-refresh'].includes(data.label)||!Number.isSafeInteger(data.ordinal)||data.ordinal<1||data.ordinal>64||!['start','end','elapsed'].every(key=>phaseNumber(data[key]))||data.end<data.start)return;
   names.push('ordinal','start','end','elapsed');Object.assign(row,{ordinal:data.ordinal,start:data.start,end:data.end,elapsed:data.elapsed});
   if(data.label==='author-execute'){if(typeof data.pin!=='string'||!/^[a-f0-9]{64}$/.test(data.pin))return;names.push('pin');row.pin=data.pin;}
   if(!ownKeysExactly(data,names))return;
  }else if(data.kind==='resource'){
   if(data.label!=='compiled-resource'||!['derived-html','profile','runtime'].includes(data.resource)||typeof data.pin!=='string'||!/^[a-f0-9]{64}$/.test(data.pin)||!['request_start','headers_at','text_at','verified_at','elapsed'].every(key=>phaseNumber(data[key]))||data.headers_at<data.request_start||data.text_at<data.headers_at||data.verified_at<data.text_at||!Number.isSafeInteger(data.http_status)||data.http_status<100||data.http_status>599||!Number.isSafeInteger(data.text_utf16)||data.text_utf16<0||data.text_utf16>67108864)return;
   names.push('resource','pin','request_start','headers_at','text_at','verified_at','elapsed','http_status','text_utf16');for(const name of names.slice(11))row[name]=data[name];if(!ownKeysExactly(data,names))return;
  }else return;
  phase_generation=data.sequence;phase_time_origin=data.timeOrigin;phase_clock.push(row);
 }
