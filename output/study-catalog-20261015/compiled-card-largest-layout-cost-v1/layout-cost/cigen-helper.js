/* Local to the serialized installCigen realm; no FRAME closure references. */
 const qaNames=['refresh','layout','iframeSelector','firstGeometry','styleBlock','repeatGeometry'];
 let qaEnabled=false,qaFinalDepth=0;
 const qaCosts={batchFinallyCount:0,batchFinallyMs:0,batchIframeSelectorMs:0,batchFirstGeometryMs:0,batchStyleBlockMs:0,batchRepeatGeometryMs:0};
 for(const name of qaNames){qaCosts[name+'Count']=0;qaCosts[name+'Ms']=0}
 function qaNow(){try{const value=win.performance.now();return Number.isFinite(value)?value:0}catch(_){return 0}}
 function qaMeasure(name,action){if(!qaEnabled)return action();const started=qaNow();qaCosts[name+'Count']++;try{return action()}finally{const elapsed=Math.max(0,qaNow()-started);qaCosts[name+'Ms']+=elapsed;if(qaFinalDepth&&['iframeSelector','firstGeometry','styleBlock','repeatGeometry'].includes(name))qaCosts['batch'+name[0].toUpperCase()+name.slice(1)+'Ms']+=elapsed}}
 function qaCostReset(){for(const name of Object.keys(qaCosts))qaCosts[name]=0;qaFinalDepth=0;qaEnabled=true}
 function qaCostSeal(){qaEnabled=false;return Object.freeze({...qaCosts})}
