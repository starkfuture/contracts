#!/usr/bin/env python3
"""Assemble build/app: the upstream files our patches change (patched) plus overlay/.

    python3 tools/assemble.py [upstream-src-dir]

Without a source dir it downloads the upstream tag named in UPSTREAM. PINS stops the build for a
human review when DocuSeal changes under us: it holds the sha256 of every patched upstream file and
of the permission rules Stark replaces for non-admins. Any change there must be re-read against the
intent in FORK.md before the patch is redone and the pin updated.
"""
import hashlib, io, os, re, shutil, subprocess, sys, tarfile, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = dict(re.findall(r"^(\w+)=(\S+)$", open(os.path.join(ROOT, "UPSTREAM")).read(), re.M))
OUT = os.path.join(ROOT, "build", "app")


def upstream_src(tmp):
    if len(sys.argv) > 1:
        return sys.argv[1]
    url = f"https://codeload.github.com/docusealco/docuseal/tar.gz/refs/tags/{UP['TAG']}"
    with tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url, timeout=120).read())) as t:
        t.extractall(tmp, filter="data")
    return os.path.join(tmp, f"docuseal-{UP['TAG']}")


with tempfile.TemporaryDirectory() as tmp:
    src = upstream_src(tmp)
    for line in open(os.path.join(ROOT, "PINS")):
        digest, path = line.split()
        if hashlib.sha256(open(os.path.join(src, path), "rb").read()).hexdigest() != digest:
            sys.exit(f"PINS: upstream {path} changed. Re-read it against FORK.md, redo its patch if any, then update PINS.")
    work = os.path.join(tmp, "work")
    shutil.copytree(src, work, symlinks=True)
    changed = []
    for patch in sorted(os.listdir(os.path.join(ROOT, "patches"))):
        p = os.path.join(ROOT, "patches", patch)
        r = subprocess.run(["patch", "-p1", "--forward", "--fuzz=0", "--no-backup-if-mismatch", "-i", p],
                           cwd=work, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"{patch} does not apply to {UP['TAG']}:\n{r.stdout}{r.stderr}")
        changed += re.findall(r"^\+\+\+ b/(\S+)", open(p).read(), re.M)
    shutil.rmtree(OUT, ignore_errors=True)
    for path in changed:
        os.makedirs(os.path.dirname(os.path.join(OUT, path)), exist_ok=True)
        shutil.copy(os.path.join(work, path), os.path.join(OUT, path))
    shutil.copytree(os.path.join(ROOT, "overlay"), OUT, dirs_exist_ok=True)

files = sorted(os.path.relpath(os.path.join(d, f), OUT) for d, _, fs in os.walk(OUT) for f in fs)
print(f"build/app: {len(files)} files ({len(changed)} patched upstream, {len(files) - len(changed)} Stark)")
for f in files:
    print("  ", f)
