"""Reversible startup overlay for the composed, source-verified library runtime.

Frozen source evidence is input only. This changes scheduling, never source
data, routes, integrity pins, classification, or counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MARKER = "/* library-startup-responsive.v1 */"
CSS_SOURCE = Path(__file__).resolve().parents[1] / "anki_pipeline/templates/sense-frequency.css"


def disclosure_css():
    selectors = (".sf-report summary.sf-row::after{", ".sf-report .sf-sense[open]>summary.sf-row::after{")
    lines = CSS_SOURCE.read_text().splitlines()
    matches = [line for line in lines if line.startswith(selectors)]
    if len(matches) != 2 or any("content:'⌄'" in line or "content:'⌃'" in line for line in matches):
        raise ValueError("shared disclosure CSS boundary changed")
    return "".join(matches)


def optimize_runtime(source: str) -> tuple[str, dict]:
    original_source = source
    css = disclosure_css()
    if MARKER in source:
        raise ValueError("startup overlay is already present")
    edits = []

    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("startup overlay source boundary is not unique")
        source = source.replace(old, new, 1)
        edits.append([old, new])

    replace("async function validateSource(source) {", "async function validateSource(source, hashText) {")
    replace("if (await sha(source.english) !== source.english_hash || await sha(source.translation) !== source.translation_hash)",
            "if (await hashText(source.english) !== source.english_hash || await hashText(source.translation) !== source.translation_hash)")
    start = source.index("  async function prepare(data) {")
    end = source.index("  async function load(pin, options) {", start)
    original = source[start:end]
    updated = original.replace("await sha(", "await checkedSha(").replace("await validateSource(chunk.source);", "await validateSource(chunk.source, checkedSha);")
    anchor = "    var copy = JSON.parse(JSON.stringify(data)), index = new Map(), mappings = 0, unmapped = 0;"
    scheduling = '''
    // SHA results are scoped to this immutable snapshot; every expected hash
    // is still checked, including repeated text with a different claimed hash.
    var hashes = new Map(), work = 0, started = window.Date.now();
    async function checkedSha(text) {
      if (hashes.has(text)) return hashes.get(text);
      // A microtask-only SHA fallback otherwise starves input and paint until
      // thousands of checks finish. Yield a real task, even on an HTTP LAN.
      if (++work >= 128 || window.Date.now() - started >= 8) {
        await new Promise(function (resolve) { window.setTimeout(resolve, 0); });
        work = 0; started = window.Date.now();
      }
      var result = sha(text);
      hashes.set(text, result);
      try { return await result; }
      catch (error) { hashes.delete(text); throw error; }
    }
'''
    if updated.count(anchor) != 1:
        raise ValueError("projection snapshot boundary changed")
    updated = updated.replace(anchor, anchor + scheduling)
    replace(original, updated)
    anchor = "    var wholeHandle = window.AnkiFineChunkRuntime.install(cardDocument);"
    replace(anchor, anchor + '''
    // Only truly empty cards skip optional example sidecars. Any native/SF
    // candidate still takes the complete pinned validation path below.
    var card = cardsById.get(state.cardId);
    if (card && card.exampleCount === 0 && !cardDocument.querySelector(
        '.sf-sentence-pair,.sf-example,.sf-source-preview,.sf-year-preview,.example-card,li._r28')) {
      state.frame.setAttribute('data-owned-runtime-state', 'ready');
      return function () {
        wholeHandle.dispose(); state.frame.removeAttribute('data-owned-runtime-state');
      };
    }
''')
    replace("    style.textContent = responsiveCardCss;",
            "    style.textContent = responsiveCardCss + " + json.dumps(css) + ";")
    optimized = MARKER + "\n" + source
    restored = optimized[len(MARKER) + 1:]
    for old, new in reversed(edits):
        if restored.count(new) != 1:
            raise ValueError("startup inverse boundary changed")
        restored = restored.replace(new, old, 1)
    if restored != original_source:
        raise ValueError("startup inverse is not the exact original")
    return optimized, {"schema": "library-startup-responsive.v1", "inverse": edits,
        "before_sha256": hashlib.sha256(restored.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(optimized.encode()).hexdigest(),
        "inverse_exact": True, "disclosure_css_sha256": hashlib.sha256(css.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    original = args.source.read_bytes()
    if args.expected_sha256 and hashlib.sha256(original).hexdigest() != args.expected_sha256:
        parser.error("source SHA changed")
    optimized, receipt = optimize_runtime(original.decode("utf-8"))
    if args.receipt and args.receipt.exists():
        parser.error("receipt already exists")
    if args.output:
        if args.output.exists():
            parser.error("output already exists; preserve the prior artifact")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(optimized)
    else:
        print(optimized, end="")
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
