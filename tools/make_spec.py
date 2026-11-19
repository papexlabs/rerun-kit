#!/usr/bin/env python3
"""Write a unit's file (papex-rerun-spec/v1) for a Lean 4 proof in a public repository.

  python3 tools/make_spec.py SEED.json OUT.spec.json

SEED.json holds everything but the file list: schema, system, title, repo, commit, projectDir,
toolchain, leanCommit, theorems, permittedAxioms, outputs, statementFile, diskGb, expectedSeconds,
and buildTargets when `lake build` must be told what to build (lakefile.toml names no defaultTargets).
This tool fetches the repository at the commit into a temporary folder (it builds nothing and runs
nothing of it), lists the tracked files under projectDir and writes their SHA-256 values into
"files". It also prints the manifest line for the unit. It writes nothing if the kit's own check
(the unit's file, the files Lake reads, then the text search) would stop a run of this unit.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rerun  # noqa: E402  (the kit next to this tool, for its check)


def git(folder, *args):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": folder, "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", "-C", folder, *args], check=True, capture_output=True, text=True, env=env).stdout


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    with open(sys.argv[1]) as fh:
        spec = json.load(fh)
    with tempfile.TemporaryDirectory() as folder:
        git(folder, "init", "-q", ".")
        git(folder, "remote", "add", "origin", spec["repo"])
        git(folder, "fetch", "-q", "--depth", "1", "origin", spec["commit"])
        git(folder, "checkout", "-q", "--detach", "FETCH_HEAD")
        if git(folder, "rev-parse", "HEAD").strip() != spec["commit"]:
            sys.exit("the fetched commit is not the one the seed names")
        files = {}
        for name in git(folder, "ls-files", "--", spec["projectDir"] or ".").split("\n"):
            if name:
                path = os.path.join(folder, name)
                if os.path.islink(path):
                    sys.exit(f"{name} is a link; a unit's files must be plain files")
                with open(path, "rb") as fh:
                    files[name] = hashlib.sha256(fh.read()).hexdigest()
        spec["files"] = dict(sorted(files.items()))
        rerun.check_spec(spec, sys.argv[1])  # stops, as a run would, on a field the kit cannot read
        found = rerun.scan_source(folder, spec)
        if found:
            sys.exit("The kit would stop a run of this unit:\n" + "\n".join("  " + f for f in found[:40]))
    raw = (json.dumps(spec, indent=1, ensure_ascii=False) + "\n").encode()
    with open(sys.argv[2], "wb") as fh:
        fh.write(raw)
    unit = os.path.basename(sys.argv[2])[:-len(".spec.json")]
    print(json.dumps({"key": unit, "kind": "run", "expectedSeconds": spec.get("expectedSeconds", 300),
                      "inputSha256": "0x" + hashlib.sha256(raw).hexdigest()}, separators=(",", ":")))


if __name__ == "__main__":
    main()
