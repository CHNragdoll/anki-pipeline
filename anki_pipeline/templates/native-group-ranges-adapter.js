// Only call after the existing host verifies this audited original/prepared module.
function adaptNativeGroupRanges(code, originalPin) {
  if (!["5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"].includes(originalPin)) return code;
  var edits = [["    return { text: el.textContent, nodes: nodes };", "    return { root: el, text: el.textContent, nodes: nodes };"], ["      for (var el = part.node.parentElement; el && el !== part.node.ownerDocument; el = el.parentElement) {\n        if (!el.contains(part.node) || !predicate(el)) continue;", "      for (var el = part.node.parentElement; el; el = el === view.root ? null : el.parentElement) {\n        if (!predicate(el)) continue;"], ["ranges(view, function (el) { return el.classList.contains('card-chunk') && paragraph.contains(el); })", "ranges(view, function (el) { return el.classList.contains('card-chunk'); })"], ["ranges(textView(en), function (el) { return el.matches('mark.target-word') && en.contains(el); })", "ranges(textView(en), function (el) { return el.matches('mark.target-word'); })"]];
  if (edits.some(function (edit) { return code.split(edit[0]).length !== 2; })) throw Error('Audited native group ranges boundary differs');
  edits.forEach(function (edit) { code = code.replace(edit[0], edit[1]); });
  return code;
}
