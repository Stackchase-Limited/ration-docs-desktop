#!/usr/bin/env bash
# Publish the fork to github.com/Stackchase-Limited.
#
# Everything the binaries were built from goes public, in one pass, so that the
# "View Corresponding Source" link in the About box resolves to the revision that
# actually produced them - which is what AGPL s.6 asks for and what a link to lab02
# (sign-in required) never delivered.
#
#   ./tools/publish-to-github.sh            # print what would happen, change nothing
#   ./tools/publish-to-github.sh --run      # create repositories and push
#
# Requires: gh authenticated as an account that can create repositories in the
# organisation. Check with:  gh api /orgs/Stackchase-Limited/memberships/<user>
set -euo pipefail

ORG="${ORG:-Stackchase-Limited}"
TAG="${TAG:-v2026.1.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN=0
[ "${1:-}" = "--run" ] && RUN=1

# submodule path -> repository name. The names match lab02 so the two remotes stay
# recognisably the same repositories.
REPOS="
core:ration-docs-core
sdkjs:ration-docs-sdkjs
web-apps:ration-docs-web-apps
desktop-apps:ration-docs-desktop-apps
desktop-sdk:ration-docs-desktop-sdk
dictionaries:ration-docs-dictionaries
build_tools:ration-docs-build-tools
.:ration-docs-desktop
"

say() { printf '%s\n' "$*"; }
run() { if [ "$RUN" = 1 ]; then eval "$@"; else say "    would run: $*"; fi; }

for entry in $REPOS; do
	path="${entry%%:*}"
	name="${entry##*:}"
	dir="$ROOT/$path"
	git -C "$dir" rev-parse --git-dir >/dev/null 2>&1 || { say "skip $path (not a git checkout)"; continue; }

	branch="$(git -C "$dir" branch --show-current)"
	head="$(git -C "$dir" rev-parse --short HEAD)"
	say "$name  <- $path  branch=$branch  head=$head"

	# A dirty tree would publish something no commit describes.
	if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
		say "    REFUSING: uncommitted changes in $path"
		continue
	fi

	if gh repo view "$ORG/$name" >/dev/null 2>&1; then
		say "    repository exists"
	else
		run "gh repo create '$ORG/$name' --public --description 'Ration Docs Desktop - $name'"
	fi

	run "git -C '$dir' remote remove github 2>/dev/null || true"
	run "git -C '$dir' remote add github 'https://github.com/$ORG/$name.git'"
	# Only our branch. The upstream branches (61 to 134 of them per repository) are
	# ONLYOFFICE's to publish and add nothing to the source offer.
	run "git -C '$dir' -c credential.helper= push github '$branch'"
	run "gh repo edit '$ORG/$name' --default-branch '$branch'"
	# The tag is what /source points at: the exact revision the binaries came from.
	run "git -C '$dir' tag -f '$TAG' HEAD"
	run "git -C '$dir' -c credential.helper= push -f github '$TAG'"
done

say ""
say "After this, .gitmodules still points at lab02. Repoint it with:"
say "    tools/repoint-submodules.sh github    (or lab02 to go back)"
say "and commit the result, so a clone of the public repository resolves publicly."
