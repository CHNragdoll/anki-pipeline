from pathlib import Path
import hashlib,json,difflib
D=Path(__file__).resolve().parent
sha=lambda raw:hashlib.sha256(raw).hexdigest()
raw=(D/'baseline-candidate-frame.js').read_bytes();old=raw.decode();assert sha(raw)=='052ccc54d5f0c799a890d504fe48b695a6c547f5d96b96943d4f8ab472afa59d'
frame=old;edits=[]
def edit(before,after):
 global frame
 assert frame.count(before)==1, before[:150]
 frame=frame.replace(before,after,1);edits.append([before,after])
helper=(D/'transport.js').read_text();edit('async function resource(url,pin,phase){',helper+"async function resource(url,pin,phase,deliveryRule=null){if(deliveryRule!==null)compiledArtifactTransport.validate(deliveryRule,url,pin);")
edit("phase?.asset(pin,'start');const preparedModule=", "phase?.asset(pin,'start');if(deliveryRule!==null)return compiledArtifactTransport.read(deliveryRule,url,pin,phase,typeof frameAbort!=='undefined'?frameAbort.signal:undefined);const preparedModule=")
edit('return resource(new URL(value.src,document.baseURI).href,value.sha256,phase)', 'return resource(new URL(value.src,document.baseURI).href,value.sha256,phase,value)')
prefix='const compiledAssets=';at=frame.index(prefix)+len(prefix);assets,n=json.JSONDecoder().raw_decode(frame[at:]);before=frame[at:at+n]
for entry in assets['entries'].values():
 for name in ('html','profile'):
  item=entry[name];assert set(item)=={'src','sha256'};item['gzipSrc']=item['src']+'.gz'
item=assets['runtime'];assert set(item)=={'src','sha256'};item['gzipSrc']=item['src']+'.gz'
after=json.dumps(assets,ensure_ascii=False,separators=(',',':'));edit(prefix+before,prefix+after)
edit('const compiledProfiles=makeCompiledProfileSupport(', 'const compiledArtifactTransport=createCompiledArtifactTransport(compiledAssets,document,(...args)=>fetch(...args),knownPinMatches,globalThis);\nconst compiledProfiles=makeCompiledProfileSupport(')
edit("const key=url+'|'+pin;if(scriptCache.has(key))return scriptCache.get(key);","const key=url+'|'+pin;if(scriptCache.has(key)){if(deliveryRule===null)return scriptCache.get(key);const deliverySignal=typeof frameAbort!=='undefined'?frameAbort.signal:undefined,text=await scriptCache.get(key);compiledArtifactTransport.validate(deliveryRule,url,pin);if(deliverySignal?.aborted)throw deliverySignal.reason||new DOMException('Compiled resource request was superseded','AbortError');return text}")
undo=frame
for before,after in reversed(edits):assert undo.count(after)==1;undo=undo.replace(after,before,1)
assert undo==old
html=(D/'baseline-candidate-frame.html').read_text();assert html.count(old)==1
output=html.replace(old,frame,1);assert output.replace(frame,old,1)==html
for name,body in [('candidate-frame.js',frame),('candidate-frame.html',output),('edits.json',json.dumps(edits,indent=2)+'\n'),('compiled-assets.json',json.dumps(assets,indent=2)+'\n')]: (D/name).write_text(body)
(D/'transport-only.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),frame.splitlines(True),fromfile='baseline052ccc',tofile='candidate-transport-only')))
print(json.dumps({'edits':len(edits),'frame':sha(frame.encode()),'html':sha(output.encode()),'inverse_frame':sha(undo.encode()),'inverse_html':sha(html.encode()),'same_source_chain':True,'same_cache24_proof':True}))
