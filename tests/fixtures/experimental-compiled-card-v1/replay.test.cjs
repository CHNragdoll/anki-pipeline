'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const {verifyProfile}=require('./verify.cjs'),{createHash}=require('node:crypto'),{gunzipSync}=require('node:zlib');
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const legacy=path.join(__dirname,'authors/');
const rows=[['abolish','36d114906f1f97c4c7d3bf7070a8b35ec213e037106f759edd395633e3d50ee3','c05c0dae50a25cb40e4d3284e1f73b9036a2c3767669b0267c64c30ff09dbc62'],['train','761dddf2d5aa11495f624c8bdb41fe583bf604f07026152d8f93ac94f90e2854','bf29cde53d96fdf0f1f276ec90b7b230fabc49212397716f8e9a56915d10d947']];
for(const[name,id,pin]of rows)test(name+' actual source-preserving replay binds by semantic regions, not whole-document offsets',()=>{
 const html=gunzipSync(fs.readFileSync(path.join(__dirname,'replay',name,'body.html.gz'))).toString('utf8');assert.equal(sha(html),pin);
 const profile=JSON.parse(fs.readFileSync(path.join(__dirname,name,'profile.json'),'utf8'));profile.bindings.derivedHTMLSha256=pin;const raw=JSON.stringify(profile),anchors={schema:profile.schema,version:1,profileSha256:sha(raw),htmlSha256:pin,bindings:profile.bindings};
 const authenticated=verifyProfile(raw,html,anchors),dom=new JSDOM(html,{runScripts:'outside-only'}),w=dom.window,d=w.document;
 try{w.PointerEvent=w.MouseEvent;w.eval(fs.readFileSync(legacy+'sense-filter.js','utf8'));w.eval(fs.readFileSync(legacy+'author-chunks.js','utf8'));w.eval(fs.readFileSync(path.join(__dirname,'runtime.js'),'utf8'));const h=w.AnkiCompiledCardRuntime.install(d,authenticated,{isCurrent:()=>true});
 d.head.insertAdjacentHTML('beforeend','<style>body{color:inherit}</style><script type="text/plain">host source placeholder</script>');d.body.prepend(d.createComment('host footer/base/source nodes differ'));assert.equal(h.refresh(),true);
 const spec=authenticated.nodeBindings.find(s=>s.roles.includes('sf-member')),member=d.querySelector('[data-study-compiled-key="'+spec.key+'"]');member.parentElement.append(member);const changed=d.body.innerHTML;assert.throws(()=>h.refresh(),/semantic|position/);assert.equal(d.body.innerHTML,changed);h.dispose();
 }finally{w.close()}
});
