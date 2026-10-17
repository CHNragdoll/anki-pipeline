// The complete runtime must first pass resource SHA verification and valid().
function adaptCompiledFrozenProfile(code,pin){
 if(pin!=='e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc')return code;
 const edits=[[
 " 'use strict';\n const KEY=",
 " 'use strict';\n const compiledFrozenProfileReader=typeof root.__studyCompiledFrozenProfileCapture==='function'?root.__studyCompiledFrozenProfileCapture():null;\n const KEY="
 ],[
 '  const profile=JSON.parse(JSON.stringify(input));',
 "  const verifiedFrozenProfile=typeof compiledFrozenProfileReader==='function'?compiledFrozenProfileReader(doc,input):null;\n  const profile=verifiedFrozenProfile===input?input:JSON.parse(JSON.stringify(input));"
 ]];
 if(code.includes('compiledFrozenProfileReader')||edits.some(([before])=>code.split(before).length!==2))throw Error('Audited compiled frozen profile boundary differs');
 for(const [before,after]of edits)code=code.replace(before,after);return code;
}
