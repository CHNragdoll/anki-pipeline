/* Prewarm only unique indexed English present in the collected text strings.
 * Full original module integrity is verified by the existing caller first.
 * buildIndex, digest/cache and all actual process validators remain byte-exact. */
function adaptSharedReadingBankWarm(code, originalPin) {
  const approved = [
    '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',
    'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93', 'b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26', '286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67'
  ];
  if (!approved.includes(originalPin)) return code;
  const before = 'warm:async function(metadata,texts){await buildIndex(metadata);await Promise.all(texts.map(digest));}';
  const after = 'warm:async function(metadata,texts){var index=await buildIndex(metadata),bound=new Set(),seen=new Set(),jobs=[];index.bindings.forEach(function(entry){bound.add(entry.binding.english);});texts.map(function(text){if(typeof text!=="string"){jobs.push(digest(text));return;}if(bound.has(text)&&!seen.has(text)){seen.add(text);jobs.push(digest(text));}});await Promise.all(jobs);}';
  if (code.split(before).length !== 2 || code.includes(after)) {
    throw Error('Audited shared reading bank warm boundary differs');
  }
  return code.replace(before, after);
}
