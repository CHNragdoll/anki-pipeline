/* Proposed compiled capability primitive only. The caller must authenticate
 * rawCss/attrs and capture the exact owned source/approved-author style nodes.
 * This function does NOT itself authorize skipping numbering or bind a view. */
function compiledNumberingCSSMatches(doc,records,isCurrent){
 try{
  if(typeof isCurrent!=='function'||!isCurrent()||!doc?.defaultView||!Array.isArray(records)||!records.length||records.length>16)return false;
  const win=doc.defaultView,Sheet=win.CSSStyleSheet;
  if(typeof Sheet!=='function'||typeof Sheet.prototype?.replaceSync!=='function')return false;
  const adopted=doc.adoptedStyleSheets;
  if(adopted!==undefined&&(!Number.isSafeInteger(adopted.length)||adopted.length!==0))return false;
  const sheets=Array.from(doc.styleSheets);if(sheets.length!==records.length)return false;
  const seen=new Set();let units=0;
  for(let n=0;n<records.length;n++){
   const record=records[n],node=record?.node,sheet=sheets[n];
   if(!node||seen.has(node)||node.ownerDocument!==doc||!doc.contains(node)||node.tagName!=='STYLE'||sheet.ownerNode!==node||node.sheet!==sheet)return false;
   seen.add(node);
   if(typeof record.rawCss!=='string'||!Array.isArray(record.attrs)||/@import\b/i.test(record.rawCss))return false;
   units+=record.rawCss.length;if(units>1048576)return false;
   if(node.textContent!==record.rawCss||JSON.stringify(Array.from(node.attributes,a=>[a.name,a.value]))!==JSON.stringify(record.attrs)||sheet.disabled!==false||sheet.media?.mediaText!=='')return false;
   const expected=new Sheet();expected.replaceSync(record.rawCss);
   const wanted=Array.from(expected.cssRules,r=>r.cssText),actual=Array.from(sheet.cssRules,r=>r.cssText);
   if(wanted.length!==actual.length||wanted.some((text,i)=>typeof text!=='string'||text!==actual[i]))return false;
  }
  return isCurrent()===true;
 }catch(_){return false}
}
