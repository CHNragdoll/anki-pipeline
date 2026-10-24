'use strict';
const {FIRST,PIN}=require('./build.cjs');
const boundary=';\ndocument.querySelectorAll(\'[class]\')';
const guard=";\nvar compiledCodecCheck=typeof window.__studyCompiledCodecCapture==='function'?window.__studyCompiledCodecCapture():null;\nif(compiledCodecCheck&&compiledCodecCheck(document,config,'"+PIN+"')===true)return;\ndocument.querySelectorAll('[class]')";
const adapted=FIRST.replace(boundary,guard);if(adapted===FIRST)throw Error('Codec guard boundary');
function adapt(code,pin){if(pin!==PIN)return code;if(!code.startsWith(FIRST)||code.split(FIRST).length!==2||code.includes('var compiledCodecCheck='))throw Error('Audited compiled codec boundary differs');return adapted+code.slice(FIRST.length)}
function inverse(code){if(!code.startsWith(adapted)||code.split(adapted).length!==2)throw Error('Codec inverse boundary');return FIRST+code.slice(adapted.length)}
const injected=guard.slice(1,guard.lastIndexOf("\ndocument.querySelectorAll"));
function inverseComposed(code){if(code.split(injected).length!==2)throw Error('Composed codec inverse boundary');return code.replace(injected,'')}
module.exports={adapt,inverse,inverseComposed,FIRST,adapted};
