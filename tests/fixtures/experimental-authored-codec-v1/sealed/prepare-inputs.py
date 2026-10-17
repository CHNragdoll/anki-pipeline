from pathlib import Path
import hashlib,json
r=Path('/tmp/study-compiled-authored-codec-20261017-uoX8mppA')
p=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v3/media/_study_9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba.js')
b=p.read_bytes();assert hashlib.sha256(b).hexdigest()=='9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba'
s=b.decode();end=s.index('\n})();')+len('\n})();');first=s[:end];assert s[end:].startswith('\n(function(){')
(r/'source-9014.js').write_bytes(b);(r/'first-iife.js').write_text(first)
f=Path('/tmp/study-compiled-frozen-profile-reuse-20261017-gs235ciw/candidate-frame.js').read_text();at=f.index('const compiledInitialNumberingCertificate=')+len('const compiledInitialNumberingCertificate=');certificate=json.JSONDecoder().raw_decode(f[at:])[0]
(r/'cohort.json').write_text(json.dumps(certificate['cohort'],indent=2)+'\n')
(r/'base-profile.json').write_bytes(Path('/tmp/study-compiled-frozen-profile-reuse-20261017-gs235ciw/fixture-profile.json').read_bytes())
(r/'actual-small-compiled.html').write_bytes(Path('/tmp/study-compiled-frozen-profile-reuse-20261017-gs235ciw/fixture-input.html').read_bytes())
print(json.dumps({'first_iife_sha256':hashlib.sha256(first.encode()).hexdigest(),'source_bytes':len(b),'first_bytes':len(first.encode()),'cohort':len(certificate['cohort'])}))
