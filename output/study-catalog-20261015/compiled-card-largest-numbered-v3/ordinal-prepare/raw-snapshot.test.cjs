'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const source=fs.readFileSync(__dirname+'/apply-large-v2.cjs','utf8');
const start=source.indexOf('let sourceRaw=fs.readFileSync(sourcePath);');
const end=source.indexOf('console.log(',start);
assert.ok(start>=0&&end>start);
const read=new Function('fs','h','q','assert','sourcePath',source.slice(start,end)+'return source;');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
let reads=0;function run(bytes,pin=sha(bytes)){reads=0;return read({readFileSync(path){assert.equal(path,'owned-input');reads++;return bytes;}},{SHA:sha},{SOURCE:pin},assert,'owned-input');}
for(const raw of [Buffer.from('中文🧪\n'),Buffer.from([0xef,0xbb,0xbf,0x61])]){assert.equal(Buffer.compare(Buffer.from(run(raw)),raw),0);assert.equal(reads,1);}
const invalid=Buffer.from([0xc3,0x28]);assert.throws(()=>run(invalid),e=>e instanceof TypeError&&/encoded data|encoding/i.test(e.message));assert.equal(reads,1);
assert.throws(()=>run(Buffer.from('valid'),'0'.repeat(64)),/Source raw-byte snapshot SHA/);assert.equal(reads,1);
console.log(JSON.stringify({passed:true,actual_source_read_block:true,valid_utf8_and_bom_byte_exact:true,matching_pin_invalid_utf8_rejected:true,wrong_raw_sha_rejected:true,one_read:true}));
