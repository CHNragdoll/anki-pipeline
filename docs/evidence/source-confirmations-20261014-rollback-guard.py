"""Restore the exact approved runner for an explicitly approved rollback.

This recovery artifact has not been executed against the actual candidate.
Run only after the renderer has exited; preserve this immutable driver pair.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
OWNED = ROOT / 'output/source-confirmations-20261014/cards-own'
DRIVER = ROOT / 'scripts/apply_source_confirmations.py'
APPROVED = ROOT / 'docs/evidence/source-confirmations-20261014-approved-apply-driver.py'
APPROVED_SHA = 'dcd2249383ef66d6e2a3ca7a610efa707dee76fd4d7009aba125510472a20981'
RENDER_SHA = '89f4a4ef9156c17aa8479086c19718e18dfebf199b575252da1fe9c0475b3c2c'
PLAN = OWNED / 'prepared-v5-final-plan.json'
PLAN_SHA = 'be28346ed841773d2e1838146d83166bcdd7d2a786e1ee995bb8145612a995cb'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def replace(raw, mode):
    handle, name = tempfile.mkstemp(prefix='.source-confirmations-recovery-', dir=DRIVER.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, DRIVER)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-rollback-approved', action='store_true', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    receipt = args.receipt.resolve()
    require(receipt.is_relative_to(OWNED) and not receipt.exists(), 'fresh owned rollback receipt required')
    require(sha(PLAN.read_bytes()) == PLAN_SHA, 'original applied plan bytes differ')
    current, approved = DRIVER.read_bytes(), APPROVED.read_bytes()
    require(sha(current) == RENDER_SHA, 'current renderer changed; refuse to overwrite user changes')
    require(sha(approved) == APPROVED_SHA, 'approved runner snapshot differs')
    mode = DRIVER.stat().st_mode & 0o777
    try:
        replace(approved, mode)
        require(sha(DRIVER.read_bytes()) == APPROVED_SHA, 'approved runner installation differs')
        subprocess.run([sys.executable, str(DRIVER), 'rollback', '--plan', str(PLAN),
            '--plan-sha256', PLAN_SHA, '--root-write-approved', '--receipt', str(receipt)], check=True, cwd=ROOT)
    finally:
        require(sha(DRIVER.read_bytes()) == APPROVED_SHA, 'runner changed concurrently; refuse to overwrite user changes')
        replace(current, mode)
        require(sha(DRIVER.read_bytes()) == RENDER_SHA, 'renderer restoration differs')


if __name__ == '__main__':
    main()
