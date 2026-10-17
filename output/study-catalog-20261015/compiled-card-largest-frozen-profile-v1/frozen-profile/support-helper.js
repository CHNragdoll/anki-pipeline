 // Only JSON parsed, binding-checked and recursively frozen load results qualify.
 const verifiedFrozenProfiles=new WeakSet();
 function rememberFrozenProfile(value){const profile=immutable(value);verifiedFrozenProfiles.add(profile);return profile}
 // One factory-lifetime reader; captures weak tables, never a request/doc/input.
 function readVerifiedFrozenProfile(doc,input){
  try{const owner=owners.get(doc);return owner&&owner.profile===input&&verifiedFrozenProfiles.has(input)&&owner.valid()===true&&current()===true?input:null}catch(_){return null}
 }
 function withFrozenCapture(win,action){
  const name='__studyCompiledFrozenProfileCapture';
  let conflict;try{conflict=name in win}catch(_){return action(false)}
  if(conflict)return action(false)
  const capture=()=>readVerifiedFrozenProfile;let installed=false;
  try{try{Object.defineProperty(win,name,{configurable:true,writable:false,value:capture});installed=true}catch(_){return action(false)}return action(true)}
  finally{if(installed)try{if(Object.getOwnPropertyDescriptor(win,name)?.value===capture)delete win[name]}catch(_){}}
 }
