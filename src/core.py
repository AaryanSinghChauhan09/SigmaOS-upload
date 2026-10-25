"""File upload / share client planner for SigmaOS-upload (mintupload-style).

The engine plans curl uploads to known share targets, enforces size limits
(parsing human-readable limits), lists targets and keeps a JSONL upload
history. Actually performing uploads is the thin side-effecting execute
layer -- self_test() only exercises the pure plan/parse/validate layer
(no network; filesystem use limited to tempfile).
Principles: Defensive Programming, Fail-Fast, Separation of Concerns, KISS.
"""
import argparse, json, os, re, sys

ENGINE = {
    "name": "sigma-upload",
    "summary": "Plan file uploads to share targets with size limits & history",
    "language": "python",
    "verbs": ["upload-plan", "targets", "size-limit", "history"],
    "principles": ["Defensive Programming", "Fail-Fast",
                   "Separation of Concerns", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-upload targets
transfer  PUT   https://transfer.sh/{name}   max=5120M
$ sigma-upload size-limit 10M
10000000 bytes
$ sigma-upload upload-plan report.pdf --target transfer --limit 50M
curl --upload-file report.pdf https://transfer.sh/report.pdf
$ sigma-upload history --store history.jsonl
report.pdf -> transfer (71234 bytes) ok
"""


class UploadError(Exception):
    pass


TARGETS = {
    "transfer": {"url": "https://transfer.sh/{name}", "method": "PUT",
                 "max_bytes": 5 * 1024 * 1024 * 1024},
    "0x0": {"url": "https://0x0.st", "method": "POST", "max_bytes": 5120 ** 3},
    "fileio": {"url": "https://file.io", "method": "POST",
               "max_bytes": 100 * 1024 * 1024},
    "litterbox": {"url": "https://litterbox.catbox.moe/resources/internals/api.php",
                  "method": "POST", "max_bytes": 1024 * 1024 * 1024},
}
_SIZE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([KMGT])(I)?B?$", re.I)
_UNITS = "KMGT"


# --------------------------------------------------------------------------- #
#  PURE plan / parse layer
# --------------------------------------------------------------------------- #
def parse_size(text):
    """Parse a human size string ('10M', '1.5GiB', '4096') into bytes."""
    if isinstance(text, (int, float)):
        if text < 0:
            raise UploadError(f"bad size: {text!r}")
        return int(text)
    s = str(text).strip()
    if s.isdigit():
        return int(s)
    m = _SIZE_RE.match(s)
    if not m:
        raise UploadError(f"bad size: {text!r} (expected e.g. 10M, 1.5GiB)")
    num = float(m.group(1))
    base = 1024 if m.group(3) else 1000
    exp = _UNITS.index(m.group(2).upper()) + 1
    return int(num * (base ** exp))


def format_size(n):
    """Render a byte count as a human-readable string (deterministic)."""
    n = int(n)
    if n < 0:
        raise UploadError("size must be >= 0")
    for unit, exp in (("GiB", 3), ("MiB", 2), ("KiB", 1)):
        step = 1024 ** exp
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def targets():
    """List the known share targets as deterministic records."""
    return [{"name": name, "url": t["url"], "method": t["method"],
             "max_bytes": t["max_bytes"],
             "max_human": format_size(t["max_bytes"])}
            for name, t in sorted(TARGETS.items())]


def upload_plan(path, target="transfer", limit=None, timeout=600):
    """Plan a curl upload; enforces per-target and caller size limits."""
    if target not in TARGETS:
        raise UploadError(f"unknown target {target!r} "
                          f"(choose from {', '.join(sorted(TARGETS))})")
    t = TARGETS[target]
    if not isinstance(path, str) or not path:
        raise UploadError("no file given")
    name = os.path.basename(path)
    if not name or name.startswith("."):
        raise UploadError(f"refusing to upload {name!r}")
    if not os.path.isfile(path):
        raise UploadError(f"no such file: {path}")
    size = os.path.getsize(path)
    max_bytes = t["max_bytes"]
    if limit is not None:
        limit = parse_size(limit)
        if limit <= 0:
            raise UploadError("size limit must be > 0")
        max_bytes = min(max_bytes, limit)
    if size > max_bytes:
        raise UploadError(f"file is {format_size(size)} but the limit is "
                          f"{format_size(max_bytes)}")
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        raise UploadError("timeout must be an integer")
    if not (1 <= timeout <= 86400):
        raise UploadError("timeout must be 1..86400 seconds")
    url = t["url"].format(name=name)
    if t["method"] == "PUT":
        argv = ["curl", "--fail", "--silent", "--show-error",
                "--max-time", str(timeout), "--upload-file", path, url]
    else:
        argv = ["curl", "--fail", "--silent", "--show-error",
                "--max-time", str(timeout), "-F", f"reqtype=fileupload",
                "-F", f"fileToUpload=@{path}", url]
    return {"argv": argv, "target": target, "url": url, "bytes": size,
            "max_bytes": max_bytes}


def size_limit(text):
    """Validate and normalise a size limit string."""
    n = parse_size(text)
    if n <= 0:
        raise UploadError("size limit must be > 0")
    return {"bytes": n, "human": format_size(n)}


# --------------------------------------------------------------------------- #
#  Upload history (JSONL; self_test uses tempfile only)
# --------------------------------------------------------------------------- #
def load_history(path):
    """Load JSONL history records; fails fast on malformed lines."""
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError as e:
                raise UploadError(f"history line {lineno}: bad JSON: {e}") from e
            if not isinstance(rec, dict) or "file" not in rec or "target" not in rec:
                raise UploadError(f"history line {lineno}: malformed record")
            records.append(rec)
    return records


def append_history(path, rec):
    """Append one upload record to the JSONL history."""
    if not isinstance(rec, dict) or not rec.get("file") or not rec.get("target"):
        raise UploadError("history record needs 'file' and 'target'")
    rec = dict(rec)
    rec.setdefault("bytes", 0)
    rec.setdefault("ok", True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return load_history(path)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    p.add_argument("--store", default=os.path.expanduser(
        "~/.local/share/sigma-upload/history.jsonl"), help="history store path")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("upload-plan", help="build a curl upload invocation")
    up.add_argument("file")
    up.add_argument("--target", default="transfer", choices=sorted(TARGETS))
    up.add_argument("--limit", default=None)
    up.add_argument("--timeout", type=int, default=600)
    sub.add_parser("targets", help="list known share targets")
    sl = sub.add_parser("size-limit", help="parse a human size limit")
    sl.add_argument("value")
    hs = sub.add_parser("history", help="show or record upload history")
    hs.add_argument("--record", default=None, metavar="FILE")
    hs.add_argument("--target", default=None, metavar="TARGET")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "upload-plan":
            plan = upload_plan(args.file, args.target, args.limit, args.timeout)
            print(" ".join(plan["argv"]))
        elif args.cmd == "targets":
            for t in targets():
                print(f'{t["name"]:<10} {t["method"]:<4} {t["url"]:<60} '
                      f'max={t["max_human"]}')
        elif args.cmd == "size-limit":
            s = size_limit(args.value)
            print(f'{s["bytes"]} bytes ({s["human"]})')
        elif args.cmd == "history":
            if args.record:
                if not args.target:
                    print("error: --record needs --target", file=sys.stderr)
                    return 1
                size = os.path.getsize(args.record) if os.path.isfile(args.record) else 0
                append_history(args.store, {"file": os.path.basename(args.record),
                                            "target": args.target,
                                            "bytes": size, "ok": True})
            for rec in load_history(args.store):
                print(f'{rec["file"]} -> {rec["target"]} '
                      f'({rec["bytes"]} bytes) '
                      f'{"ok" if rec.get("ok") else "failed"}')
        return 0
    except (UploadError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


# --------------------------------------------------------------------------- #
#  Tests (pure plan/parse layer; filesystem use limited to tempfile)
# --------------------------------------------------------------------------- #
def self_test() -> None:
    assert parse_size("4096") == 4096
    assert parse_size("10M") == 10_000_000
    assert parse_size("512K") == 512_000
    assert parse_size("1GiB") == 1024 ** 3
    assert parse_size("1.5G") == 1_500_000_000
    assert parse_size(2048) == 2048
    for bad in ("abc", "-5M", "M", "10 MB", ""):
        try:
            parse_size(bad)
        except UploadError:
            pass
        else:
            raise AssertionError(f"bad size not rejected: {bad!r}")

    assert format_size(0) == "0 B"
    assert format_size(2048) == "2.0 KiB"
    assert format_size(1536 * 1024 * 1024) == "1.5 GiB"

    names = [t["name"] for t in targets()]
    assert names == sorted(TARGETS)
    assert targets() == targets()                     # deterministic
    assert {t["name"] for t in targets()} == {"transfer", "0x0", "fileio", "litterbox"}

    s = size_limit("10M")
    assert s == {"bytes": 10_000_000, "human": "9.5 MiB"}, s
    try:
        size_limit("0")
    except UploadError:
        pass
    else:
        raise AssertionError("zero size limit not rejected")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        small = os.path.join(d, "report.pdf")
        with open(small, "wb") as fh:
            fh.write(b"%PDF-1.4 tiny report")
        plan = upload_plan(small, "transfer")
        assert plan["argv"][0] == "curl" and "--upload-file" in plan["argv"]
        assert plan["argv"][-1] == "https://transfer.sh/report.pdf"
        assert plan["bytes"] == os.path.getsize(small)
        post = upload_plan(small, "0x0")
        assert "-F" in post["argv"] and "fileToUpload=@ "not in post["argv"]
        assert any(a.startswith("fileToUpload=@") for a in post["argv"])
        # size-limit enforcement (pure validation, no network)
        try:
            upload_plan(small, "transfer", limit="1")
        except UploadError as e:
            assert "limit" in str(e)
        else:
            raise AssertionError("over-limit upload not rejected")
        try:
            upload_plan(small, "nosuch-target")
        except UploadError:
            pass
        else:
            raise AssertionError("unknown target not rejected")
        try:
            upload_plan(os.path.join(d, "missing.pdf"))
        except UploadError:
            pass
        else:
            raise AssertionError("missing file not rejected")
        hidden = os.path.join(d, ".hidden")
        open(hidden, "wb").close()
        try:
            upload_plan(hidden)
        except UploadError:
            pass
        else:
            raise AssertionError("hidden file not rejected")

        hist = os.path.join(d, "history.jsonl")
        assert load_history(hist) == []               # missing store -> empty
        append_history(hist, {"file": "report.pdf", "target": "transfer",
                              "bytes": 19, "ok": True})
        append_history(hist, {"file": "clip.mp4", "target": "0x0"})
        records = load_history(hist)
        assert [r["file"] for r in records] == ["report.pdf", "clip.mp4"]
        assert records[1]["ok"] is True and records[1]["bytes"] == 0
        with open(hist, "a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        try:
            load_history(hist)
        except UploadError:
            pass
        else:
            raise AssertionError("malformed history line not rejected")
        try:
            append_history(hist, {"file": "", "target": ""})
        except UploadError:
            pass
        else:
            raise AssertionError("empty history record not rejected")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
