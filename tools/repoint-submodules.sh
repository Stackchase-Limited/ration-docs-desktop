#!/usr/bin/env bash
# Point .gitmodules at lab02 or at GitHub.
#
# The two remotes hold the same repositories under the same names; which one the
# superproject records decides whether `git clone --recursive` works for someone
# outside the company. A public repository whose submodules resolve to a
# sign-in-only host publishes a tree that cannot be built, which is the failure the
# About box's source link used to have.
#
#   ./tools/repoint-submodules.sh github
#   ./tools/repoint-submodules.sh lab02
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-}"
case "$target" in
	github) base="https://github.com/Stackchase-Limited" ;;
	lab02)  base="https://lab02.ration.works/ration" ;;
	*) echo "usage: $0 github|lab02" >&2; exit 2 ;;
esac

cd "$ROOT"
changed=0
while read -r key url; do
	[ -n "$key" ] || continue
	name="$(basename "$url" .git)"
	new="$base/$name.git"
	[ "$url" = "$new" ] && continue
	git config -f .gitmodules "$key" "$new"
	changed=$((changed + 1))
done < <(git config -f .gitmodules --get-regexp '^submodule\..*\.url$')

git submodule sync --quiet
echo "repointed $changed submodule url(s) at $base"
git config -f .gitmodules --get-regexp '^submodule\..*\.url$' | sed 's/^/  /'
