#!/usr/bin/env python3
"""
#2389 - "I am bombarded with all sorts of junk notifications every day."

The "make me your default application" prompt exists in two forms. The modal form
carries a "Do not show this message again" checkbox, and that checkbox is the only
thing that ever stops it. The toast form - the one users actually get, since
notifications are supported on every Windows this ships to - has two buttons and no
checkbox.

And the answer given to the toast was discarded. The notification callback re-enters
Association::AssociationPrivate::showAssociationMessage with the result; at HEAD that
result matches neither the DLG_RESULT_NONE branch nor MODAL_RESULT_YES, so the
function falls through both and returns having recorded nothing. chekForAssociations
lets the prompt through again a day later, and again the day after, for as long as any
supported format is associated with something else - which, for somebody who keeps a
different default editor on purpose, is forever.

The fix reads an explicit No from the toast as the checkbox the toast could not draw.
The distinction that matters is which results count: NOTIF_FAILED means the toast never
appeared and the modal is about to be shown, so silencing the prompt there would stop it
without the user ever having seen it, and an unrecognised action (-1, what the toast
handler returns for a button it cannot map) or a dismissal is not an answer at all.

This extracts the real notificationAnswerStopsAsking by brace matching and compiles it
against the real headers, so MODAL_RESULT_* and NOTIF_FAILED are the shipped constants.

BASELINE=1 re-reads association.cpp from git, where no such decision exists: every
answer is dropped and the prompt returns tomorrow. That is the defect.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
SRCDIR = os.path.join(REPO, 'win-linux/src')
REL = 'win-linux/src/platform_win/association.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '865159a5fd^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

at = source.find('static bool notificationAnswerStopsAsking(')
if at == -1:
    sys.stderr.write(
        'notificationAnswerStopsAsking not found in %s.\n'
        'The toast form of the "set default application" prompt has no opt-out and\n'
        "throws the user's answer away, so the prompt comes back every day (#2389).\n"
        % REL)
    sys.exit(1)

open_brace = source.index('{', at)
depth = 0
for i in range(open_brace, len(source)):
    if source[i] == '{':
        depth += 1
    elif source[i] == '}':
        depth -= 1
        if depth == 0:
            fn = source[at:i + 1]
            break

# The decision is worthless if nothing consults it, and it must not be applied to the
# modal, which has a checkbox of its own.
if not re.search(r'fromNotification\s*&&\s*notificationAnswerStopsAsking\(result\)', source):
    sys.stderr.write('%s never consults notificationAnswerStopsAsking on the '
                     'notification path\n' % REL)
    sys.exit(1)
if not re.search(r'reg_user\.setValue\("ignoreAssocMsg",\s*true\)', source):
    sys.stderr.write('%s never records the opt-out\n' % REL)
    sys.exit(1)

harness = r'''
#include "components/cnotification.h"
#include <stdio.h>

%s

static int failures = 0;
static void check(int result, bool want, const char *why) {
    bool got = notificationAnswerStopsAsking(result);
    printf("  result=%%-3d %%-40s stops asking=%%-5s %%s\n", result, why,
           got ? "yes" : "no", got == want ? "ok" : "FAILED");
    if (got != want) failures++;
}

int main() {
    check(MODAL_RESULT_NO,       true,  "the user pressed No");

    check(MODAL_RESULT_YES,      false, "the user pressed Yes - associate instead");
    check(NOTIF_FAILED,          false, "the toast never appeared - modal follows");
    check(-1,                    false, "an action the handler could not map");
    check(MODAL_RESULT_CANCEL,   false, "cancelled, not answered");
    check(MODAL_RESULT_SKIP,     false, "some other dialog's answer");
    check(MODAL_RESULT_REMIND,   false, "some other dialog's answer");
    check(MODAL_RESULT_OK,       false, "some other dialog's answer");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - No stops the prompt for good; a toast that failed or was ignored does not");
    return failures ? 1 : 0;
}
''' % fn

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    Q = '/opt/homebrew/opt/qt@5'
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, src,
                        '-I' + SRCDIR,
                        '-I' + Q + '/lib/QtCore.framework/Headers',
                        '-F' + Q + '/lib', '-framework', 'QtCore'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
