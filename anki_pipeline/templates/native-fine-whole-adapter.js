// Call only after existing original/prepared native source verification.
function adaptNativeFineWholeProbe(code, originalPin) {
  if (["5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e", "be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93", "b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26", "286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67"].indexOf(originalPin) === -1) return code;
  var edits = [["      var chunks = Array.from(root.querySelectorAll('[data-chunk-ids],[data-chunk-sentence-ids]')).filter(function (chunk) {\n        return isNative(chunk, root);\n      });", "      var chunks = Array.from(root.querySelectorAll('[data-chunk-sentence-ids]')).filter(function (chunk) {\n        return isNative(chunk, root);\n      });"], ["      if (!whole.size) return; // Absence of metadata never makes a singleton a whole sentence.\n      stats.rootsWithWhole++;", "      if (!whole.size) return; // Absence of metadata never makes a singleton a whole sentence.\n      chunks = Array.from(root.querySelectorAll('[data-chunk-ids],[data-chunk-sentence-ids]')).filter(function (chunk) {\n        return isNative(chunk, root);\n      });\n      stats.rootsWithWhole++;"]];
  if (edits.some(function (edit) { return code.split(edit[0]).length !== 2; })) throw Error('Audited Fine whole probe boundary differs');
  edits.forEach(function (edit) { code = code.replace(edit[0], edit[1]); });
  return code;
}
