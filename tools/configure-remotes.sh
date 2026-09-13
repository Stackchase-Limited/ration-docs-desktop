#!/bin/sh
# Put the submodule remotes into the layout this fork requires, and make pushing to
# ONLYOFFICE fail locally rather than depend on anyone remembering not to.
#
#   tools/configure-remotes.sh            # apply
#   tools/configure-remotes.sh --check    # report only, exit 1 if wrong
#
# Why this exists: .git/config is not tracked, so a fresh clone comes back with `origin`
# pointing at ONLYOFFICE for core, sdkjs, web-apps and desktop-sdk - and an ordinary
# `git push` in one of those submodules is then aimed at upstream. That has been attempted
# once already; it failed only because the account lacks permission, which is not a safety
# margin worth relying on.
#
# The layout:
#   upstream = ONLYOFFICE, fetch only, push URL deliberately invalid
#   origin   = lab02, the only place this fork's work goes
#
# desktop-apps and dictionaries already have lab02 as origin and are left alone.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LAB02=https://lab02.ration.works/ration
CHECK=${1:-}

# submodule : the lab02 project it should push to
set -- \
  "core:ration-docs-core" \
  "sdkjs:ration-docs-sdkjs" \
  "web-apps:ration-docs-web-apps" \
  "desktop-sdk:ration-docs-desktop-sdk"

rc=0
for entry in "$@"; do
  mod=${entry%%:*}
  proj=${entry#*:}
  dir="$ROOT/$mod"
  [ -d "$dir/.git" ] || [ -f "$dir/.git" ] || { echo "  $mod: not a checkout, skipped"; continue; }

  cur_origin=$(git -C "$dir" remote get-url origin 2>/dev/null || echo "")

  if [ "$CHECK" = "--check" ]; then
    case "$cur_origin" in
      *github.com/ONLYOFFICE*) echo "  $mod: WRONG - origin still points at ONLYOFFICE"; rc=1 ;;
      "")                      echo "  $mod: no origin (lab02 project not created yet)" ;;
      *lab02.ration.works*)    echo "  $mod: ok - origin is lab02" ;;
      *)                       echo "  $mod: origin is $cur_origin"; rc=1 ;;
    esac
    continue
  fi

  # move an ONLYOFFICE origin out of the way
  case "$cur_origin" in
    *github.com/ONLYOFFICE*)
      git -C "$dir" remote rename origin upstream
      ;;
  esac

  if git -C "$dir" remote | grep -qx upstream; then
    git -C "$dir" remote set-url --push upstream "DO-NOT-PUSH-to-ONLYOFFICE-use-lab02"
  fi

  # Only add origin once the lab02 project exists; pointing at a missing project would
  # turn every push into a confusing 404 instead of a clear "not set up yet".
  if ! git -C "$dir" remote | grep -qx origin; then
    if git ls-remote --heads "$LAB02/$proj.git" >/dev/null 2>&1; then
      git -C "$dir" remote add origin "$LAB02/$proj.git"
      echo "  $mod: origin -> $LAB02/$proj.git"
    else
      echo "  $mod: $LAB02/$proj.git does not exist yet - origin not set"
    fi
  fi
done

[ "$CHECK" = "--check" ] && exit $rc
echo ""
echo "Done. 'git push' in those submodules now fails locally until lab02 has a project."
exit 0
