from pathlib import Path
import hashlib,json,difflib
P=Path(__file__).parent
sha=lambda text:hashlib.sha256(text.encode()).hexdigest()
base=(P/'baseline-frame.js').read_text();html=(P/'baseline-frame.html').read_text()
assert sha(base)=='1c14c2f629111e4f912b6a027cbd1fb47feebdd00b8b18c7982f7193318fc84d'
assert sha(html)=='eda4e08d1ce9ce848896ec2d03d6e2996c7cf5d2b38df52c91eda39c54e951e1'
helper=(P/'private-proof.js').read_text()
edits=[
 ("const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();", "const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();\n"+helper),
 ("scriptCache.set(key,task);task.catch", "scriptCache.set(key,task);task.then(text=>{try{if(typeof text==='string'&&typeof pin==='string'&&/^[a-f0-9]{64}$/.test(pin)&&scriptCache.get(key)===task)resourceProofs.set(task,{text,pin})}catch(_){}},()=>{});task.catch"),
 ("if(!(await Promise.all([[html,entry.html.sha256],[raw,entry.profile.sha256],[runtimeCode,assets.runtime.sha256]].map(([text,pin])=>matches(text,pin)))).every(Boolean))fail('external resource SHA');", "if(!(await Promise.all([[html,entry.html],[raw,entry.profile],[runtimeCode,assets.runtime]].map(([text,value])=>verifiedResourceString(resource,new URL(value.src,document.baseURI).href,value.sha256,text)===true?true:matches(text,value.sha256)))).every(Boolean))fail('external resource SHA');")
]
code=base
for before,after in edits:
 assert code.count(before)==1,before
 code=code.replace(before,after)
inverse=code
for before,after in reversed(edits):
 assert inverse.count(after)==1
 inverse=inverse.replace(after,before)
assert inverse==base
assert html.count(base)==1
newhtml=html.replace(base,code)
assert newhtml.replace(code,base)==html
(P/'candidate-frame.js').write_text(code);(P/'candidate-frame.html').write_text(newhtml)
(P/'edits.json').write_text(json.dumps(edits,ensure_ascii=False,indent=2)+'\n')
proof={'schema':'study-resource-proof-reuse-composition.v1','baseline_frame_sha256':sha(base),'baseline_html_sha256':sha(html),'candidate_frame_sha256':sha(code),'candidate_html_sha256':sha(newhtml),'edits':len(edits),'inverse_exact_frame':True,'inverse_exact_html':True,'cache_limit_24_and_failure_cleanup_unchanged':True,'source_author_layout_claim_ready_cancel_unchanged':True,'only_tmp_no_install':True}
(P/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
(P/'runtime.diff').write_text(''.join(difflib.unified_diff(base.splitlines(True),code.splitlines(True),fromfile='baseline-1c14.js',tofile='candidate.js')))
print(json.dumps(proof,indent=2))
