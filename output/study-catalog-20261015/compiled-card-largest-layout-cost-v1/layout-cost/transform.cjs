'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const edits=JSON.parse(fs.readFileSync(__dirname+'/edits.json','utf8'));
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
const BASE='bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816';
const CANDIDATE='1c14c2f629111e4f912b6a027cbd1fb47feebdd00b8b18c7982f7193318fc84d';
module.exports={adapt(source){assert.equal(sha(source),BASE);for(const e of edits){assert.equal(source.split(e.before).length,2,e.label);source=source.replace(e.before,e.after)}assert.equal(sha(source),CANDIDATE);return source},undo(source){assert.equal(sha(source),CANDIDATE);for(const e of [...edits].reverse()){assert.equal(source.split(e.after).length,2,e.label);source=source.replace(e.after,e.before)}assert.equal(sha(source),BASE);return source}};
