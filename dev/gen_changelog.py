# -*- coding: utf-8 -*-
"""Generate changelog.txt (repo root) from git history.

Keeps only commits whose subject starts with "גרסה " (format:
"גרסה 3.63 — description..."), one block per version (newest wins), newest first:

    ## 3.63
    <text after the dash, plus body lines>

Usage:
    python dev/gen_changelog.py
    python dev/gen_changelog.py --prepend 3.64 "גרסה 3.64 — ..."   # release.py:
        the commit being shipped is not in git yet, so its note goes on top.
"""
import argparse
import io
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(REPO, "changelog.txt")
SEP = "---END---"
TRAILER_RE = re.compile(r"^(Co-Authored-By|Signed-off-by|Generated with)\b", re.I)
SUBJECT_RE = re.compile(r"^גרסה\s+(\d+(?:\.\d+)*)\s*[—–\-:]*\s*(.*)$", re.S)


def parse_entry(text):
    """'גרסה 3.63 — desc\\nbody' → (version, note) or None."""
    text = (text or "").strip()
    subject, _, body = text.partition("\n")
    m = SUBJECT_RE.match(subject.strip())
    if not m:
        return None
    note = m.group(2).strip()
    # Drop git trailers / credits (old commits carried them).
    body = "\n".join(
        ln for ln in body.splitlines()
        if not TRAILER_RE.match(ln.strip())).strip()
    if body:
        note = (note + "\n" + body).strip()
    return m.group(1), note


def git_entries():
    raw = subprocess.run(
        ["git", "log", "--format=%s%n%b" + SEP], cwd=REPO,
        capture_output=True, check=True).stdout.decode("utf-8", "replace")
    out = []
    for chunk in raw.split(SEP):
        e = parse_entry(chunk)
        if e:
            out.append(e)
    return out


def build(entries):
    seen, blocks = set(), []
    for ver, note in entries:
        if ver in seen or not note:
            continue
        seen.add(ver)
        blocks.append("## " + ver + "\n" + note + "\n")
    return "\n".join(blocks)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prepend", nargs=2, metavar=("VERSION", "MESSAGE"))
    p.add_argument("-o", "--out", default=OUT)
    a = p.parse_args()
    entries = git_entries()
    if a.prepend:
        ver, msg = a.prepend
        e = parse_entry(msg) or (ver, msg.strip())
        entries.insert(0, (ver, e[1]))
    txt = build(entries)
    with io.open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("changelog: %d versions -> %s" % (txt.count("\n## ") + (1 if txt.startswith("## ") else 0), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
