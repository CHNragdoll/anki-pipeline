'use strict';
const assert=require('node:assert/strict');
const {JSDOM}=require('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/node_modules/jsdom');
const B=require('./build.cjs'),{fixture,parentFor}=require('./contracts.cjs');
const earlier="document.body.dataset.earlierSawCompact=String(!!document.querySelector('._r11'))";
const input=fixture.replace('<body>','<body><script>'+earlier+'</script>');
function observe(html){const d=new JSDOM(html,{runScripts:'outside-only'});try{d.window.eval(earlier);d.window.eval(B.FIRST);return{earlierSawCompact:d.window.document.body.dataset.earlierSawCompact,html:d.window.document.documentElement.outerHTML}}finally{d.window.close()}}
const built=B.build(input,parentFor(input));
assert.equal(built.profile.authoredCodec.eligible,false);
const original=observe(input),candidate=observe(built.html);
assert.equal(original.earlierSawCompact,'true');
assert.equal(candidate.earlierSawCompact,original.earlierSawCompact,'unknown earlier script must observe original compact DOM');
assert.equal(built.html,input,'unsupported actual source cohort must preserve input bytes');
assert.equal(built.edits.length,0);assert.equal(B.patch(built.html,built.inverse),input);
assert.deepEqual(B.scriptLexemes(built.html),B.scriptLexemes(input));assert.deepEqual(candidate,original);
const parameter=B.build(fixture,parentFor(fixture),[B.PIN]);assert.equal(parameter.profile.authoredCodec.eligible,false);assert.equal(parameter.html,fixture);assert.equal(parameter.edits.length,0);
const accepted=B.build(fixture,parentFor(fixture));assert.equal(accepted.profile.authoredCodec.eligible,true);assert.ok(accepted.edits.length>0);
console.log('PASS unknown actual/declared cohort: no pre-evaluation, source bytes and earlier observation unchanged; approved cohort still compiled');
