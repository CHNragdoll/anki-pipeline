/* Only after original resource SHA and common legacy->canonical adaptation. */
function adaptCompiledInitialNumbering(code,originalPin){
 const pins=['9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1','ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'];
 if(!pins.includes(originalPin))return code;
 if(code!==canonicalExampleNumberingSource)throw Error('Audited canonical numbering source differs');
 const edits=[['  var installed = new WeakMap();','  var installed = new WeakMap();\n  var compiledInitialNumbering = null;\n  if (typeof window.__studyCompiledInitialNumberingCapture === "function") compiledInitialNumbering = window.__studyCompiledInitialNumberingCapture();'],['    installed.set(root, handle); refresh();','    installed.set(root, handle);\n    var compiledInitialAccepted = false;\n    try { compiledInitialAccepted = typeof compiledInitialNumbering === "function" && compiledInitialNumbering(root) === true; } catch (_) {}\n    if (!compiledInitialAccepted) refresh();']];
 if(code.includes('compiledInitialNumbering')||edits.some(([before])=>code.split(before).length!==2))throw Error('Audited compiled initial numbering boundary differs');for(const [before,after]of edits)code=code.replace(before,after);return code;
}
