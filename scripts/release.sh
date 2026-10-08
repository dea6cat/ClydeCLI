#!/usr/bin/env bash
# Raise the version, tag it and push: scripts/release.sh patch|minor|major|X.Y.Z
# Bumps pyproject.toml, src/__init__.py and uv.lock, turns CHANGELOG [Unreleased] into the new release,
# commits "Release vX.Y.Z", tags it (annotated) and pushes main and the tag.
set -euo pipefail
cd "$(dirname "$0")/.."

arg="${1:-}"
[[ -n "$arg" ]] || { echo "usage: scripts/release.sh patch|minor|major|X.Y.Z" >&2; exit 2; }

[[ "$(git branch --show-current)" == "main" ]] || { echo "Release from main (you are on $(git branch --show-current))." >&2; exit 1; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "Tracked files have uncommitted changes; commit or stash them." >&2; exit 1; }
git fetch -q origin main --tags
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "main differs from origin/main; pull or push first." >&2; exit 1; }

old="$(python3 -c 'import re,sys;print(re.search(r"^version = \"(.+?)\"",open("pyproject.toml").read(),re.M).group(1))')"
new="$(python3 - "$old" "$arg" <<'PY'
import re, sys
old, arg = sys.argv[1:]
major, minor, patch = map(int, old.split("."))
if arg == "major": print(f"{major + 1}.0.0")
elif arg == "minor": print(f"{major}.{minor + 1}.0")
elif arg == "patch": print(f"{major}.{minor}.{patch + 1}")
elif re.fullmatch(r"\d+\.\d+\.\d+", arg): print(arg)
else: sys.exit("version must be patch, minor, major or X.Y.Z")
PY
)"
tag="v$new"
[[ "$new" != "$old" ]] || { echo "Already at $old." >&2; exit 1; }
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && { echo "Tag $tag already exists." >&2; exit 1; }
grep -q '^## \[Unreleased\]' CHANGELOG.md || { echo "CHANGELOG.md has no [Unreleased] section." >&2; exit 1; }

python3 - "$old" "$new" <<'PY'
import datetime, pathlib, re, sys
old, new = sys.argv[1:]

def sub(path, pattern, repl, flags=0):
    p = pathlib.Path(path)
    text, n = re.subn(pattern, repl, p.read_text(), count=1, flags=flags)
    if n != 1:
        sys.exit(f"{path}: version line not found")
    p.write_text(text)

sub("pyproject.toml", r'^version = "[^"]+"', f'version = "{new}"', re.M)
sub("src/__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{new}"', re.M)
sub("uv.lock", r'(name = "clyde-cli"\nversion = )"[^"]+"', rf'\1"{new}"')

log = pathlib.Path("CHANGELOG.md")
text = log.read_text().replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {datetime.date.today()}", 1)
link = f"[{new}]: https://github.com/dea6cat/ClydeCLI/releases/tag/v{new}"
text = text.replace(f"[{old}]: ", f"{link}\n[{old}]: ", 1) if f"[{old}]: " in text else text.rstrip("\n") + f"\n{link}\n"
log.write_text(text)
PY

git add pyproject.toml src/__init__.py uv.lock CHANGELOG.md
git commit -q -m "Release $tag"
git tag -a "$tag" -m "ClydeCLI $new"
git push origin main "$tag"
echo "Released $tag ($old -> $new)."
