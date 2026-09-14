#!/bin/sh
# #2445 - the shipped ooxmlsignature.dll imported an entry point the kernel beside
# it did not export, and the loader refused to start the app.
#
# The mangled name in the report, ?Encode@CBase64Converter@NSFile@@SA_NPEAEHAEAPEADAEAHK@Z,
# has PEAE for its first parameter - a non-const BYTE*. core a84491cf74 (2025-07-10)
# changed that parameter to const BYTE*, which changes the mangled name. So that DLL
# was built against a header older than the kernel it shipped with.
#
# Our own build is consistent (checked: kernel exports EPKhi, ooxmlsignature imports
# EPKhi, nothing imports the stale form), so there is no source fix to make. What was
# missing is anything that would have *noticed*. This builds both halves of that
# mismatch for real with clang++ and checks that build_tools/scripts/check_symbol_closure.py
# fails on the stale pairing and passes on the rebuilt one.
set -e
cd "$(dirname "$0")"
CHECK=../../build_tools/scripts/check_symbol_closure.py

rm -rf payload-bad payload-good
mkdir -p payload-bad payload-good

case "$(uname -s)" in
  Darwin) SO=dylib; DYN="-dynamiclib"; LOOSE="-undefined dynamic_lookup" ;;
  *)      SO=so;    DYN="-shared -fPIC"; LOOSE="" ;;
esac

# shellcheck disable=SC2086
clang++ $DYN -o payload-bad/libkernel.$SO kernel.cpp
# shellcheck disable=SC2086
clang++ $DYN $LOOSE -o payload-bad/libsignature.$SO signature_stale.cpp
cp payload-bad/libkernel.$SO payload-good/
# shellcheck disable=SC2086
clang++ $DYN $LOOSE -o payload-good/libsignature.$SO signature_good.cpp

echo "--- stale pairing: the checker must fail ---"
if python3 "$CHECK" payload-bad; then
  echo "FAIL: the checker passed a payload with a stale import" >&2
  exit 1
fi

echo
echo "--- rebuilt pairing: the checker must pass ---"
python3 "$CHECK" payload-good

echo
echo "ok - the checker catches the #2445 mismatch and clears the rebuilt payload"
