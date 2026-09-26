"""Check portable project records and source formats without local study data."""
from pathlib import Path
import ast
import json
import tomllib
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
standard = ROOT / "docs/project-standard"
profile = json.loads((ROOT / "docs/project-profile.json").read_text())
jsonschema.validate(profile, json.loads((standard / "schemas/project-profile.schema.json").read_text()))
ids = {c["id"] for c in json.loads((standard / "control-catalog.json").read_text())["controls"]}
actual = [c["controlId"] for c in profile["applicability"]]
assert len(actual) == len(set(actual)) and set(actual) == ids
for path in (ROOT / "anki_pipeline").glob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
assert project["version"] == "3.0.0rc1"
assert "<script" not in (ROOT / "anki_pipeline/templates/style.css").read_text().lower()
for image in ("card-preview-desktop.png", "card-preview-mobile.png"):
    assert (ROOT / "assets/screenshots" / image).stat().st_size > 1000
conformance = ROOT / "docs/conformance.json"
if conformance.exists():
    record = json.loads(conformance.read_text())
    jsonschema.validate(record, json.loads((standard / "schemas/conformance.schema.json").read_text()))
    assert {c["controlId"] for c in record["controls"]} == ids
print(f"PASS: source syntax, version, template separation, screenshots and {len(ids)} control mappings")
