"""Read-only verification of this bounded archive; no DOM or contract rerun."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    repository = base.parents[2]
    raw = (base / "manifest.json").read_bytes()
    if sha(raw) != args.expected_manifest_sha256:
        raise ValueError("External archive manifest SHA differs")
    manifest = json.loads(raw)
    for row in manifest["owned_file_seals"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Non-relative archive member")
        current = repository
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("Symlink archive member")
        data = current.read_bytes()
        if len(data) != row["bytes"] or sha(data) != row["sha256"]:
            raise ValueError(f"Archive member differs: {relative}")
    fixture = repository / "tests/fixtures/experimental-authored-codec-v1"
    spec = importlib.util.spec_from_file_location("authored_codec_archive_verifier", fixture / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_archive_seals()
    values, _ = module.source_inputs()
    actual = json.loads((base / "actual-portable-report.json").read_bytes())
    assert actual["base_contract_groups"] == 14
    assert actual["focused_p2_programs"] == 2
    assert actual["exact_code_html_authors_inverse"] is True
    assert actual["exact_portability_inverse"] is True
    assert actual["historical_noninstallable_executed"] is False
    print(json.dumps({"manifest_sha256": sha(raw),
                      "owned_files_verified_excluding_manifest": len(manifest["owned_file_seals"]),
                      "source_files_verified": len(values),
                      "recorded_contracts": "14+2 passed; this verification does not rerun them",
                      "exact_inverse_proof_recorded": True,
                      "no_product_imports_or_data_writes": True}, indent=2))


if __name__ == "__main__":
    main()
