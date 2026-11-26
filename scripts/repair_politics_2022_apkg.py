"""Repair Issue #87 in the distributed deck without changing card identities."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

FIELD_SEPARATOR = "\x1f"
CHOICE = re.compile(r'<p class="paragraph">答案[：:]\s*([A-D]+)</p>$')
HINT = re.compile(r'(<p class="paragraph">答题思路[：:]</p>.+)(</div>)$', re.S)
ANSWER = re.compile(r'【答案】\s*([A-D]+)')
TITLE = re.compile(r'2022 · (单选题|多选题|材料分析题) · 第 (\d+) 题')


def repair(fields):
    match = TITLE.fullmatch(fields[0])
    if match is None:
        return None
    title, front, back, *_ = fields
    number = int(match[2])
    if number <= 33:
        printed = CHOICE.search(front)
        key = ANSWER.search(back)
        if printed is None or key is None:
            raise ValueError(f"Unexpected choice answer boundary: {title}")
        # Match the checked answer PDF where the question source printed a different key.
        verified = {17: "BCD", 19: "ABD"}
        if key[1] != verified.get(number, printed[1]):
            raise ValueError(f"Unexpected answer key: {title}")
        return number, front[:printed.start()], back
    hint = HINT.search(front)
    if hint is None or not back:
        raise ValueError(f"Unexpected explanation boundary: {title}")
    return (number, front[:hint.start()] + hint[2],
            back + '<section class="embedded-answer-note">' + hint[1] + '</section>')


def watermark(db, signer, key_dir, public_key):
    faces = []
    payloads = []
    for note_id, guid, value in db.execute("select id,guid,flds from notes order by id"):
        fields = value.split(FIELD_SEPARATOR)
        indexes = (1, 2) if len(fields) == 6 else (1,)
        edited = repair(fields)
        if edited:
            _, fields[1], fields[2] = edited
        for index in indexes:
            payloads.append({
                "project": "anki-pipeline",
                "artifact_id": "politics-issue87-20261126",
                "kind": "anki-html-field",
                "content_id": f"{guid}:{index}",
                "content_sha256": hashlib.sha256(fields[index].encode()).hexdigest(),
            })
        faces.append((note_id, indexes, fields, edited))
    assert sorted(edited[0] for _, _, _, edited in faces if edited) == list(range(1, 39))

    with tempfile.TemporaryDirectory() as folder:
        payload, signed, checked = (Path(folder) / name for name in ("payload.json", "signed.json", "checked.json"))
        payload.write_text(json.dumps(payloads))
        command = [sys.executable, str(signer)]
        subprocess.run([*command, "sign", "--input", str(payload), "--output", str(signed),
                        "--public-key", str(public_key), "--key-dir", str(key_dir)], check=True)
        subprocess.run([*command, "verify", "--input", str(signed), "--output", str(checked),
                        "--public-key", str(public_key)], check=True)
        tokens = json.loads(signed.read_text())
        proofs = json.loads(checked.read_text())
    assert len(tokens) == len(proofs) == len(payloads)
    for expected, proof in zip(payloads, proofs, strict=True):
        assert proof["valid"] and all(proof["payload"][k] == v for k, v in expected.items())

    index = 0
    stamp = int(time.time())
    for note_id, indexes, fields, _ in faces:
        for field in indexes:
            fields[field] += f"<!-- data-apwm={tokens[index]} -->"
            index += 1
        db.execute("update notes set flds=?,mod=max(mod+1,?) where id=?",
                   (FIELD_SEPARATOR.join(fields), stamp, note_id))
    db.commit()
    assert db.execute("pragma integrity_check").fetchone() == ("ok",)
    return len(tokens)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--signer", type=Path, required=True)
    parser.add_argument("--key-dir", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.exists():
        parser.error("Output must be a new file")
    with sqlite3.connect(":memory:") as db, zipfile.ZipFile(args.source) as source:
        db.deserialize(source.read("collection.anki2"))
        count = watermark(db, args.signer, args.key_dir, args.public_key)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as output:
            for name in source.namelist():
                output.writestr(name, db.serialize() if name == "collection.anki2" else source.read(name))
    print(f"38 repaired notes; {count} verified invisible signatures")


if __name__ == "__main__":
    main()
