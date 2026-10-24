"""Reconstruct and exercise the sealed small prototype; never import product code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


FIXTURE = Path(__file__).resolve().parent
REPOSITORY = FIXTURE.parents[2]
SOURCE_FREEZE_SHA256 = "8a57cba99652f9ed841c99c0bd1b44ee8611dc15638b1c4a0b141c8d3d2651d9"
NONINSTALLABLE = {
    "previous-drift-helper.cjs", "pre-fix-capability.cjs", "pre-fix-build.cjs"
}
PROGRAMS = (
    "contracts.cjs", "intrinsics-contract.cjs", "generation-preflight-contract.cjs"
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_file(root: Path, relative: str) -> bytes:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise ValueError(f"Non-relative fixture path: {relative}")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Symlink is not a sealed fixture: {relative}")
    current.relative_to(root)
    return current.read_bytes()


def source_inputs() -> tuple[dict[str, bytes], dict]:
    raw = checked_file(FIXTURE, "source-FROZEN.json")
    if digest(raw) != SOURCE_FREEZE_SHA256:
        raise ValueError("Original external freeze pin differs")
    freeze = json.loads(raw)
    rows = json.loads(checked_file(FIXTURE, "source-files.json"))["files"]
    original = {r["path"]: r for r in freeze["files"]}
    if len(original) != 50 or len(rows) != 50 or {r["source_path"] for r in rows} != set(original):
        raise ValueError("The complete 50-file source mapping is required")
    if set(freeze["historicalNoninstallable"]) != NONINSTALLABLE:
        raise ValueError("Unsafe historical files must remain NONINSTALLABLE")
    values = {}
    for row in rows:
        name = row["source_path"]
        expected = original[name]
        if row["storage"] == "repository-reference":
            if not row["path"].startswith("tests/fixtures/"):
                raise ValueError("Only existing test fixtures may be referenced")
            root = REPOSITORY
        elif row["storage"] == "fixture":
            root = FIXTURE
        else:
            raise ValueError("Unknown fixture storage")
        data = checked_file(root, row["path"])
        if len(data) != expected["bytes"] or digest(data) != expected["sha256"]:
            raise ValueError(f"Source pin differs: {name}")
        if row["bytes"] != expected["bytes"] or row["sha256"] != expected["sha256"]:
            raise ValueError(f"Source mapping pin differs: {name}")
        values[name] = data
    return values, freeze


def check_archive_seals() -> None:
    manifest = json.loads(checked_file(FIXTURE, "manifest.json"))
    expected = {r["path"]: r for r in manifest["fixture_files"]}
    actual = {str(p.relative_to(FIXTURE)) for p in FIXTURE.rglob("*") if p.is_file()}
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("Fixture file membership differs")
    for relative, row in expected.items():
        raw = checked_file(FIXTURE, relative)
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise ValueError(f"Archive pin differs: {relative}")
    test = manifest["independent_test"]
    raw = checked_file(REPOSITORY, test["path"])
    if digest(raw) != test["sha256"] or len(raw) != test["bytes"]:
        raise ValueError("Independent test pin differs")


def main() -> None:
    check_archive_seals()
    originals, freeze = source_inputs()
    ledger = json.loads(checked_file(FIXTURE, "portability-edits.json"))
    if ledger["temporary_only"] is not True or len(ledger["edits"]) != 4:
        raise ValueError("Only four explicit dependency/verifier path edits are allowed")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required; no dependency installation is performed")
    if not (REPOSITORY / "node_modules/jsdom/package.json").is_file():
        raise RuntimeError("Existing repository node_modules/jsdom is required")
    env = {**os.environ, "NODE_PATH": str(REPOSITORY / "node_modules")}
    results = []
    with tempfile.TemporaryDirectory(prefix="study-authored-codec-portable-") as folder:
        stage = Path(folder)
        for name, raw in originals.items():
            (stage / name).write_bytes(raw)
        # The original inverse program must inspect the unmodified build bytes,
        # while its require uses the identical algorithm with a portable import.
        (stage / "build.cjs.sealed-original").write_bytes(originals["build.cjs"])
        for edit in ledger["edits"]:
            raw = originals[edit["path"]]
            if digest(raw) != edit["original_sha256"]:
                raise ValueError("Portability source pin differs")
            before, after = edit["before"], edit["after"]
            text = raw.decode("utf-8")
            if text.count(before) != edit["count"] or text.count(after):
                raise ValueError("Dependency path boundary differs")
            portable = text.replace(before, after)
            if digest(portable.encode()) != edit["portable_sha256"]:
                raise ValueError("Portable dependency pin differs")
            if portable.replace(after, before).encode() != raw:
                raise ValueError("Dependency path inverse differs")
            (stage / edit["path"]).write_text(portable, encoding="utf-8")
        for name in ("verify-v2.cjs", *PROGRAMS):
            if name in NONINSTALLABLE:
                raise ValueError("Historical unsafe code must never be executed")
            result = subprocess.run(
                [node, str(stage / name)], cwd=stage, env=env,
                capture_output=True, text=True, timeout=90, check=False,
            )
            if result.returncode:
                raise RuntimeError(f"{name} failed ({result.returncode})\n{result.stdout}{result.stderr}")
            results.append({"program": name, "exit": result.returncode,
                            "stdout": result.stdout, "stderr": result.stderr})
        proof = json.loads(results[0]["stdout"])
        if proof != json.loads(originals["v2-proof.json"]):
            raise ValueError("Original code/HTML/authors inverse proof differs")
        if "CONTRACTS 14 CPU stopped" not in results[1]["stdout"]:
            raise ValueError("Original fourteen contract groups were not completed")
        for result in results[2:]:
            if result["stdout"].count("PASS ") != 1:
                raise ValueError("Focused P2 contract was not completed exactly once")
    print(json.dumps({
        "schema": "study-authored-codec-portable-test.v1",
        "source_freeze_sha256": SOURCE_FREEZE_SHA256,
        "source_files_verified": len(originals),
        "temporary_portability_edits": len(ledger["edits"]),
        "exact_portability_inverse": True,
        "exact_code_html_authors_inverse": True,
        "base_contract_groups": 14,
        "focused_p2_programs": 2,
        "historical_noninstallable_executed": False,
        "temporary_stage_removed": not stage.exists(),
        "programs": results,
        "scope": "Small standalone prototype; no product imports, full cohort, native ready, browser or performance acceptance",
        "historical_red_logs": "Sealed originals retained; not rerun by this portable acceptance",
        "freeze_contract_groups": freeze["contractGroups"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
