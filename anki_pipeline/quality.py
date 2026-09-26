"""Quality checks report isolated problems rather than hiding missing content."""
from pathlib import Path
from .store import connect


def quality_report(database: Path, audio: Path) -> dict:
    from .inputs import _valid_mp3
    issues = []
    with connect(database, readonly=True) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]
        cards = [dict(r) for r in conn.execute("SELECT * FROM cards ORDER BY sheet,lesson,position,id")]
        sentences = [dict(r) for r in conn.execute("SELECT s.*,c.word FROM sentences s JOIN cards c ON c.id=s.card_id ORDER BY c.word,s.original_number")]
    audio = audio.resolve()
    for card in cards:
        for key in ("phonetic", "definition"):
            if not card[key]:
                issues.append({"severity": "error", "code": f"missing_{key}", "word": card["word"], "card_id": card["id"]})
        filename = card["audio_filename"]
        path = (audio / filename).resolve()
        valid = (bool(filename) and path.is_relative_to(audio) and path.is_file()
                 and 128 <= path.stat().st_size <= 5 * 1024 * 1024)
        valid = valid and _valid_mp3(path.read_bytes())
        if not valid:
            issues.append({"severity": "error", "code": "missing_or_unsafe_audio", "word": card["word"], "card_id": card["id"]})
    for sentence in sentences:
        reason = sentence["review_reason"]
        if not sentence["accepted"] or not sentence["translation"] or reason:
            issues.append({"severity": "warning", "code": reason or "missing_translation", "word": sentence["word"],
                           "sentence_id": sentence["id"], "original_number": sentence["original_number"],
                           "text": sentence["text"], "source": sentence["source"]})
    examples = {s["card_id"] for s in sentences if s["accepted"]}
    translated = {s["card_id"] for s in sentences if s["accepted"] and s["translation"] and not s["review_reason"]}
    counts = {
        "cards": len(cards), "sentences": len(sentences), "accepted_sentences": sum(s["accepted"] for s in sentences),
        "quarantined_sentences": sum(not s["accepted"] for s in sentences),
        "cards_with_examples": len(examples), "cards_with_at_least_one_complete_example": len(translated),
        "cards_without_examples": len(cards) - len(examples),
        "pending_accepted_translations": sum(s["accepted"] and (not s["translation"] or bool(s["review_reason"])) for s in sentences),
        "errors": sum(i["severity"] == "error" for i in issues),
        "warnings": sum(i["severity"] == "warning" for i in issues),
    }
    return {"integrity": integrity, "foreign_key_errors": fk, "counts": counts, "issues": issues,
            "ok": integrity == "ok" and not fk and counts["errors"] == 0 and bool(cards)}


def cards_for_export(database: Path) -> list[dict]:
    """Keep every vocabulary card; use only aligned, complete, accepted examples."""
    with connect(database, readonly=True) as conn:
        cards = [dict(r) for r in conn.execute("SELECT * FROM cards ORDER BY sheet,lesson,position,id")]
        by_id = {card["id"]: card for card in cards}
        for card in cards:
            card["examples"] = []
        for row in conn.execute("SELECT * FROM sentences WHERE accepted=1 AND translation<>'' AND review_reason='' ORDER BY original_number,id"):
            by_id[row["card_id"]]["examples"].append({key: row[key] for key in ("text", "source", "translation")})
    return cards
