'use strict';
const fs=require('node:fs'),path=require('node:path'),z=require('node:zlib'),crypto=require('node:crypto');
const D=__dirname,hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const raw=name=>z.gunzipSync(fs.readFileSync(path.join(D,name+'.gz'))).toString();
const resources=JSON.parse(fs.readFileSync(path.join(D,'resources.json')));
function resource(row){const value=raw(row.storage.replace(/\.gz$/,''));if(Buffer.byteLength(value)!==row.bytes||hash(value)!==row.sha256)throw Error('Pinned small resource differs');return value}
function byPin(pin){const row=resources.find(r=>r.sha256===pin);if(!row)throw Error('Unknown resource pin');return resource(row)}
function byPath(name){const row=resources.find(r=>r.path===name);if(!row)throw Error('Unknown resource path');return resource(row)}
module.exports={raw,hash,byPin,byPath,resources,D};
