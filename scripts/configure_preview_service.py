"""Keep the existing bookshelf responsive under macOS background I/O pressure.

This changes only the launchd scheduling class of the named bookshelf service.
It does not install a new server, alter its ports, move progress, or expose paths.
Configuration updates are backed up and compare-and-swap protected for rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile


LABEL = "com.chnragdoll.anki-bookshelf"


def responsive_configuration(raw: bytes) -> bytes:
    value = plistlib.loads(raw)
    if not isinstance(value, dict) or value.get("Label") != LABEL:
        raise ValueError("Only the existing Anki bookshelf service is supported")
    if value.get("ProcessType") not in {"Background", "Interactive"}:
        raise ValueError("Unexpected bookshelf scheduling policy")
    if value["ProcessType"] == "Interactive":
        return raw
    value["ProcessType"] = "Interactive"
    return plistlib.dumps(value, sort_keys=False)


def atomic_write(path: Path, raw: bytes, mode: int) -> None:
    """Replace one file without a partially written launchd configuration."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def runtime_preflight(raw: bytes) -> None:
    """Check the existing interpreter before stopping a working service.

    The previous server can still hold an imported module in memory after a
    development environment sync removed it from disk. Restarting first would
    turn a scheduling repair into an avoidable outage.
    """
    value = plistlib.loads(raw)
    arguments = value.get("ProgramArguments", [])
    if not arguments or not isinstance(arguments[0], str):
        raise ValueError("The existing bookshelf interpreter is missing")
    check = ("from importlib.metadata import version; "
             "import fsrs, typing_extensions; "
             "assert version('fsrs') == '6.3.2'; "
             "assert version('typing-extensions') == '4.16.0'")
    try:
        subprocess.run([arguments[0], "-c", check], check=True, timeout=20,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       cwd=value.get("WorkingDirectory"))
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Bookshelf runtime preflight failed; restore its pinned requirements before restarting") from exc


def reload_service(path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    # A failed bootout must not be followed by a second, competing service.
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)


def configure(path: Path, receipt: Path, *, reload: bool = False) -> dict:
    path = path.resolve(strict=True)
    raw = path.read_bytes()
    updated = responsive_configuration(raw)
    before = hashlib.sha256(raw).hexdigest()
    after = hashlib.sha256(updated).hexdigest()
    if updated == raw:
        return {"changed": False, "sha256": before, "label": LABEL}
    if receipt.exists():
        raise FileExistsError("Preserve the existing service receipt")
    if reload:
        runtime_preflight(updated)
    backup = path.with_name(f"{path.name}.before-{before[:16]}")
    try:
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            stream.write(raw)
    except FileExistsError:
        if backup.read_bytes() != raw:
            raise ValueError("Existing service backup does not match") from None
    mode = path.stat().st_mode & 0o777
    if path.read_bytes() != raw:
        raise ValueError("Service configuration changed during preparation")
    record = {"schema": "bookshelf.scheduling.v1", "label": LABEL,
              "path": str(path), "backup": str(backup), "before_sha256": before,
              "after_sha256": after, "mode": mode,
              "scheduling_before": "Background", "scheduling_after": "Interactive"}
    # Write the recovery record first, so interruption never loses the backup.
    with receipt.open("x", encoding="utf-8") as stream:
        os.chmod(receipt, 0o600)
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    atomic_write(path, updated, mode)
    if reload:
        try:
            reload_service(path)
        except subprocess.CalledProcessError as exc:
            # Keep the backup and receipt even when automatic recovery fails.
            # launchctl can block while another process edits this same plist.
            # Recovery must not overwrite those later, independent changes.
            try:
                current = path.read_bytes()
            except OSError:
                current = None
            if current is None or hashlib.sha256(current).hexdigest() != after:
                raise RuntimeError("Service reload failed and its configuration was subsequently edited; automatic rollback refused") from exc
            atomic_write(path, raw, mode)
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)],
                           check=False)
            raise
    return {**record, "changed": True, "reloaded": reload}


def rollback(receipt: Path, *, reload: bool = False) -> dict:
    record = json.loads(receipt.read_text(encoding="utf-8"))
    if record.get("schema") != "bookshelf.scheduling.v1" or record.get("label") != LABEL:
        raise ValueError("Unexpected service rollback receipt")
    path, backup = Path(record["path"]), Path(record["backup"])
    current, original = path.read_bytes(), backup.read_bytes()
    if hashlib.sha256(original).hexdigest() != record["before_sha256"]:
        raise ValueError("Service backup digest does not match")
    if hashlib.sha256(current).hexdigest() != record["after_sha256"]:
        raise ValueError("Service configuration was subsequently edited; rollback refused")
    responsive_configuration(original)  # Check that this is still the intended service.
    if reload:
        runtime_preflight(original)
    atomic_write(path, original, int(record["mode"]))
    if reload:
        reload_service(path)
    return {"restored": True, "path": str(path), "sha256": record["before_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plist", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        if not args.apply:
            parser.error("Rollback requires --apply")
        result = rollback(args.receipt, reload=args.reload)
    else:
        if not args.plist:
            parser.error("--plist is required")
        if args.apply:
            result = configure(args.plist, args.receipt, reload=args.reload)
        else:
            raw = args.plist.read_bytes()
            result = {"changed": responsive_configuration(raw) != raw, "applied": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
