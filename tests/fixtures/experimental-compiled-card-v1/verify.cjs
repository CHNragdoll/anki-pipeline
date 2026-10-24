'use strict';
const {createHash}=require('node:crypto');
const sha=raw=>createHash('sha256').update(raw).digest('hex');
function verifyProfile(raw,html,anchors,isCurrent=()=>true){
 if(!isCurrent())throw Error('Compiled caller cancelled');
 if(!anchors||anchors.schema!=='study-compiled-card-interactions.v1'||anchors.version!==1||!/^([a-f0-9]{64})$/.test(anchors.profileSha256||'')||!/^([a-f0-9]{64})$/.test(anchors.htmlSha256||''))throw Error('Compiled external anchor/schema invalid');
 if(sha(raw)!==anchors.profileSha256||sha(html)!==anchors.htmlSha256)throw Error('Compiled external SHA differs');
 const profile=JSON.parse(raw);if(profile.schema!==anchors.schema||profile.version!==anchors.version||JSON.stringify(profile.bindings)!==JSON.stringify(anchors.bindings)||profile.bindings.derivedHTMLSha256!==anchors.htmlSha256)throw Error('Compiled external binding differs');
 if(!isCurrent())throw Error('Compiled caller cancelled');return profile;
}
module.exports={verifyProfile};
