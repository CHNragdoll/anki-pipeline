"use strict";
const fs=require("node:fs"),crypto=require("node:crypto");
function readPinnedFieldsSnapshot(file,expected){
 if(!/^[a-f0-9]{64}$/.test(expected||""))throw Error("Invalid fields snapshot pin");
 const raw=fs.readFileSync(file);
 if(crypto.createHash("sha256").update(raw).digest("hex")!==expected)throw Error("Fields snapshot SHA differs");
 return new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(raw);
}
module.exports={readPinnedFieldsSnapshot};
