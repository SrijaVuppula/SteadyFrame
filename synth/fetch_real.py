"""Download the openly licensed real-world clips listed in data/SOURCES.md.

    python -m synth.fetch_real --out data/real

Reads the markdown table, skips the example row, downloads each URL with a checksum
file next to it, and refuses to overwrite hand-written labels. Nothing is redistributed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import urllib.request
from pathlib import Path

ROW = re.compile(r"^\|\s*(?P<id>[\w-]+)\s*\|\s*(?P<url>https?://\S+)\s*\|\s*(?P<licence>[^|]+)\|")


def parse(sources: Path) -> list[dict]:
    rows = []
    for line in sources.read_text().splitlines():
        m = ROW.match(line)
        if not m or m.group("id").startswith("(") or "example" in line:
            continue
        rows.append(m.groupdict())
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="data/SOURCES.md")
    ap.add_argument("--out", default="data/real")
    a = ap.parse_args(argv)
    rows = parse(Path(a.sources))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not rows:
        print("data/SOURCES.md has no real entries yet (see the note in it)")
        return 0
    for r in rows:
        ext = r["url"].rsplit(".", 1)[-1].split("?")[0][:4] or "mp4"
        dst = out / f"{r['id']}.{ext}"
        if dst.exists():
            print(f"{dst.name}: present")
            continue
        print(f"{r['id']}: {r['url']} ({r['licence'].strip()})")
        urllib.request.urlretrieve(r["url"], dst)
        (out / f"{r['id']}.sha256").write_text(hashlib.sha256(dst.read_bytes()).hexdigest() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
