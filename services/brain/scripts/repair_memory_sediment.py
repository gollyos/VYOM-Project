"""Retroactively apply the durable-memory retention rule.

Every verified task was being written to durable memory as a
"Completed: <utterance>" record at the verifier's own score - which was
1.0 for everything, because the structural verifier passed anything with
a non-empty response. 375 of 385 records in the live store are that
sediment, and it is not inert: MemoryRetriever ranks it alongside real
facts, so it came back as retrieval hits and was replayed to the user as
current truth.

Two consequences were observed in the user's physical-microphone session:

  * "बहुत जरूरी बात करनी है। इधर फोन करो" returned a research summary
    whose body reads "Local fixture placeholder result ... No live
    network call was made." The fixture text was not leaking from
    provider routing - it had been WRITTEN TO MEMORY during an earlier
    fixture-era run and was being served back as fact.

  * "यह क्या है?" was answered from stored business identity instead of
    the screen observation taken twenty seconds earlier.

This demotes the harmful records to SUPERSEDED, which MemoryRetriever
already skips. Nothing is deleted: the row, its content and its
provenance all survive, so historical queries and audit remain intact
(the correction/provenance rule in the control contract forbids
destroying history).

The gate applied here is the SAME one now enforced at write time in
MemoryConsolidator.from_verified_task, so the store ends up consistent
with what the runtime would produce today.

Usage:
    python scripts/repair_memory_sediment.py --dry-run
    python scripts/repair_memory_sediment.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "vyom-brain.db"

#: A serialised structure is a tool payload, not knowledge.
RAW_PAYLOAD_PREFIXES = ("{'", '{"', "[{'", '[{"')

#: Synthetic content must never be retrievable as fact.
FIXTURE_MARKERS = (
    "local fixture", "placeholder result", "no live network call",
    "mock provider", "sample data",
)

#: Commands whose outcome is true only for a moment. Storing them is what
#: made the store 97% sediment.
TRANSIENT_TITLE_MARKERS = (
    "open calculator", "close calculator", "calculator band",
    "open the chrome", "open chrome", "chrome band", "chrome off", "chrome close",
    "band karo", "close karo", "kholo", "open karo", "khol do",
    "screen pe", "screen par", "kya open hai", "what is open", "what's open",
    "active window", "window list", "show my screen", "screen dikh",
    "stop. stop", "stop stop", "ruko", "bas karo",
    "profile open", "open profile", "new tab",
)


def is_sediment(title: str, summary: str, content: str) -> tuple[bool, str]:
    """Would today's runtime refuse to write this record? Return why."""
    body = f"{summary}\n{content}".lower().strip()
    stripped = (summary or "").strip()

    if any(marker in body for marker in FIXTURE_MARKERS):
        return True, "synthetic/fixture content"
    if stripped.startswith(RAW_PAYLOAD_PREFIXES):
        return True, "raw tool payload"
    if not title.startswith("Completed:"):
        return False, ""
    goal = title[len("Completed:"):].strip().lower()
    if any(marker in goal for marker in TRANSIENT_TITLE_MARKERS):
        return True, "transient command outcome"
    return False, ""


def corrupted_fact(title: str, summary: str) -> tuple[bool, str]:
    """Identity/business slots that hold more than their own value."""
    if title not in {"User name", "User business", "User website"}:
        return False, ""
    value = (summary or "").split(":", 1)[-1].strip()
    # A name slot containing a sentence boundary or a second statement is
    # the multi-fact contamination the extractor used to produce.
    if "।" in value or "\n" in value:
        return True, "slot holds more than one statement"
    if title == "User name" and len(value.split()) > 5:
        return True, "name slot holds a sentence"
    return False, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument("--db", default=str(DB))
    args = parser.parse_args()
    apply_changes = args.apply and not args.dry_run

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = list(con.execute(
        "select id, title, summary, content, verification_state, memory_json from memories"))

    demote: list[tuple[str, str, str]] = []
    for row in rows:
        if row["verification_state"] == "superseded":
            continue
        sediment, reason = is_sediment(
            row["title"] or "", row["summary"] or "", row["content"] or "")
        if not sediment:
            sediment, reason = corrupted_fact(row["title"] or "", row["summary"] or "")
        if sediment:
            demote.append((row["id"], row["title"] or "", reason))

    by_reason: dict[str, int] = {}
    for _, _, reason in demote:
        by_reason[reason] = by_reason.get(reason, 0) + 1

    print(f"database        : {args.db}")
    print(f"total memories  : {len(rows)}")
    print(f"to demote       : {len(demote)}")
    for reason, count in sorted(by_reason.items(), key=lambda item: -item[1]):
        print(f"   {reason:<32} {count}")
    print()
    for memory_id, title, reason in demote[:12]:
        print(f"   [{reason}] {title[:70]}")
    if len(demote) > 12:
        print(f"   ... and {len(demote) - 12} more")

    if not apply_changes:
        print("\nDRY RUN - nothing written. Re-run with --apply to commit.")
        return 0

    for memory_id, _, reason in demote:
        row = con.execute(
            "select memory_json from memories where id=?", (memory_id,)).fetchone()
        try:
            payload = json.loads(row["memory_json"])
            payload["verification_state"] = "superseded"
            # Preserve WHY, so the demotion is auditable and reversible.
            payload.setdefault("provenance", []).append({
                "type": "manual_import",
                "reference": f"demoted by repair_memory_sediment: {reason}",
            })
            updated = json.dumps(payload, ensure_ascii=False)
        except Exception:
            updated = row["memory_json"]
        con.execute(
            "update memories set verification_state='superseded', memory_json=? where id=?",
            (updated, memory_id))
    con.commit()
    print(f"\nAPPLIED: {len(demote)} record(s) demoted to superseded (content preserved).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
