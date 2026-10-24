// Caller must first verify the full approved original/prepared resource SHA.
function adaptNativeGroupUnusedText(code, originalPin) {
  if (!["5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e", "be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"].includes(originalPin)) return code;
  var edits = [["    return { root: el, text: el.textContent, nodes: nodes };", "    return { root: el, nodes: nodes };"]];
  if (edits.some(function (edit) { return code.split(edit[0]).length !== 2; })) throw Error('Audited native group unused text boundary differs');
  edits.forEach(function (edit) { code = code.replace(edit[0], edit[1]); });
  return code;
}
