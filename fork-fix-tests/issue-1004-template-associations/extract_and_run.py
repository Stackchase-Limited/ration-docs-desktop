#!/usr/bin/env python3
r"""
#1004 - Windows "Default apps" did not list Ration Docs for template files, so it
could not be made the default for them, and the installer never associated them.

In our 9.4 tree .dotx itself is already there: upstream fixed its bug 46202 (the
one #1004 was filed as) by adding DOTX to the Inno Setup list, and the MSI
(package/advinst), the macOS Info.plist (CFBundleDocumentTypes) and the Linux
.desktop MimeType all carry every template type. What was still missing is the
rest of the family in the Inno installer - the one we ship: .dotm, .xltx, .xltm,
.potx, .potm, .ott, .ots, .otp were in no list in package/inno/_code.iss, so no
ProgID, no Capabilities\FileAssociations entry (which is what Settings > Default
apps lists) and no association, even with "associate all".

Fix: initExtensions() lists them (ProgIDs RationDocs.Dotm/.Xltx/.Xltm/.Potx/.Potm/
.Ott/.Ots/.Otp as in the MSI, nearest existing icon), with en/en_GB descriptions in
_messages.iss like the other recent entries. With #619 a template opened from
Explorer starts a new document, so associating them is safe.

How it is tested - the REAL installer under Wine, as issue-2031-installer-assoc-
selection does (its container scripts are reused verbatim): package/inno from
RD_REPO (or `git archive BASE_REF` with BASELINE=1) is compiled by ISCC with
/D_RATION and a stub payload, installed /VERYSILENT into a fresh prefix that
reports Windows 10.0 - once with /FULLASSOCIATION, once without - and the
registry hives are read back. Checked for every template extension: the
Capabilities\FileAssociations value (always written - it is what Default apps
shows), the ProgID's shell\open\command, and HKLM\Software\Classes\.<ext>
pointing at it with /FULLASSOCIATION and not without.

  ./extract_and_run.py             RD_REPO (default ../../desktop-apps), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL
  RD_KEEP=1                        keep the temp dir

What is NOT claimed: Wine is not Windows - Explorer, the Default apps page and
UserChoice are not exercised; the MSI is not built. The new descriptions are
English in every installer language (as extXLSM/extVSDX). Needs Docker
(amake/innosetup, linux/amd64) and network for apt-get xvfb; several minutes.
Exit 0 = pass, 1 = fail, 2 = could not run.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '867bdbe7e^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_INNO_IMAGE', 'amake/innosetup@sha256:e003376ba818547275fe10c95e2a29be0f2d12d45e9eb8f205b6672dc5685bb1')

PATHS = ['package/inno', 'package/common/license',
         'win-linux/extras/projicons/res/icons/desktopeditors.ico']

HARNESS = r"""
; Test-only wrapper: the real common.iss (+ _code.iss) plus one extra handler that,
; given /TESTSEL:<EXT,EXT,...>, puts ChlbAudio into the state the association page
; leaves it in when the user picks "Associate selected" and ticks exactly those.
#include "common.iss"

[Code]
<event('CurStepChanged')>
procedure Harness_CurStepChanged(CurStep: TSetupStep);
var
  i: Integer;
  sel: String;
begin
  if CurStep <> ssInstall then Exit;
  sel := '';
  for i := 1 to ParamCount do
    if Pos('/TESTSEL:', Uppercase(ParamStr(i))) = 1 then
      sel := ',' + Uppercase(Copy(ParamStr(i), 10, Length(ParamStr(i)))) + ',';
  if sel = '' then Exit;
  ChlbAudio := TNewCheckListBox.Create(WizardForm);
  ChlbAudio.Parent := WizardForm;
  ChlbAudio.Visible := False;
  ChlbAudio.AddRadioButton('dont', '', 0, False, True, nil);
  ChlbAudio.AddRadioButton('all',  '', 0, False, True, nil);
  ChlbAudio.AddRadioButton('sel',  '', 0, True,  True, nil);
  for i := 0 to GetArrayLength(AudioExts) - 1 do
    ChlbAudio.AddCheckBox(AudioExts[i], '', 1, Pos(',' + AudioExts[i] + ',', sel) > 0, True, False, False, nil);
  Log('HARNESS selection=' + sel);
end;
"""

ROOT_WRAP = r"""#!/bin/sh
# As root: the image ships no Xvfb, and Setup needs a display even with /VERYSILENT
# (its hidden wizard form fails with "Invalid window handle"). bullseye is on archive.debian.org.
echo "deb http://archive.debian.org/debian bullseye main
deb http://archive.debian.org/debian-security bullseye-security main" > /etc/apt/sources.list
rm -f /etc/apt/sources.list.d/*
apt-get -o Acquire::Check-Valid-Until=false update -qq >/dev/null 2>&1
apt-get install -y -qq xvfb >/dev/null 2>&1
command -v Xvfb >/dev/null || { echo XVFB-INSTALL-FAILED; exit 4; }
exec su xclient -s /bin/sh -c "PATH=/opt/bin:\$PATH WINEARCH=win32 sh /work/run.sh"
"""

CONTAINER = r"""#!/bin/sh
# Inside amake/innosetup (wine 5, 32-bit prefix). /work/src is the mirror.
export WINEDEBUG=-all
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
sleep 3
BASEPFX=/home/xclient/.wine
WINEPREFIX=$BASEPFX winecfg -v win10 >/dev/null 2>&1; WINEPREFIX=$BASEPFX wineserver -w
SYS=$BASEPFX/drive_c/windows/system32
LANGDIR="$BASEPFX/drive_c/Program Files/Inno Setup 6/Languages"
S=/work/src
for f in $(grep -o 'compiler:Languages\\[A-Za-z]*\.islu\?' $S/package/inno/common.iss | sed 's/.*\\//'); do
  [ -f "$LANGDIR/$f" ] || cp "$LANGDIR/../Default.isl" "$LANGDIR/$f"
done
mkdir -p $S/build/x86/desktop /work/out
cp $SYS/hostname.exe $S/package/inno/vc_redist.x86.exe
cp $SYS/hostname.exe $S/build/x86/desktop/RationDocs.exe
cp $SYS/hostname.exe $S/build/x86/desktop/editors.exe
cp $SYS/version.dll  $S/build/x86/desktop/dummy.dll
echo package=exe > $S/package/inno/package.config
cp /work/zz_harness.iss $S/package/inno/
cd $S/package/inno
sed -i 's/^LZMAUseSeparateProcess=yes/LZMAUseSeparateProcess=no/; s/^Compression=lzma2.*/Compression=zip/' common.iss
iscc /Q /DVERSION=9.4.0.1 /DARCH=x86 /D_RATION "/DBUILD_DIR=$(winepath -w $S/build/x86)" "/DOUTPUT_DIR=$(winepath -w /work/out)" zz_harness.iss > /work/iscc.log 2>&1
[ -f /work/out/RationDocs-9.4.0.1-x86.exe ] || { echo COMPILE-FAILED; exit 3; }
for sc in none full; do
  export WINEPREFIX=/tmp/pfx-$sc
  rm -rf $WINEPREFIX; cp -a $BASEPFX $WINEPREFIX
  wine reg add 'HKLM\Software\Classes\.pdf' /ve /d OtherVendor.PdfDoc /f >/dev/null 2>&1
  wine reg add 'HKCU\Software\Classes\.pdf' /ve /d OtherVendor.PdfDoc /f >/dev/null 2>&1
  wine reg add 'HKLM\Software\Classes\.xlsx' /ve /d OtherVendor.Sheet /f >/dev/null 2>&1
  case $sc in
    none)         extra= ;;
    sel-odt-epub) extra=/TESTSEL:ODT,EPUB ;;
    sel-docx-pdf) extra=/TESTSEL:DOCX,PDF ;;
    full)         extra=/FULLASSOCIATION ;;
  esac
  O=/work/reg/$sc; mkdir -p $O
  # Setup's own work is done when its log closes; a leftover wine process can keep
  # `wine` / `wineserver -w` waiting for ever under qemu, so wait for the log instead
  wine /work/out/RationDocs-9.4.0.1-x86.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=Z:\\tmp\\setup.log $extra >/dev/null 2>&1 &
  n=0; until grep -q 'Log closed' /tmp/setup.log 2>/dev/null || [ $n -ge 600 ]; do sleep 1; n=$((n+1)); done
  sleep 2; wineserver -k; sleep 1
  cp $WINEPREFIX/system.reg $WINEPREFIX/user.reg /tmp/setup.log $O/ 2>/dev/null
  rm -rf $WINEPREFIX /tmp/setup.log
done
"""

OURS = {'dotx': 'RationDocs.Dotx', 'dotm': 'RationDocs.Dotm', 'xltx': 'RationDocs.Xltx',
        'xltm': 'RationDocs.Xltm', 'potx': 'RationDocs.Potx', 'potm': 'RationDocs.Potm',
        'ott': 'RationDocs.Ott', 'ots': 'RationDocs.Ots', 'otp': 'RationDocs.Otp'}
CAPS = 'software\\ration\\rationdocs\\capabilities\\fileassociations'
# scenario -> associated (HKLM\Software\Classes\.<ext> = our ProgID)?
EXPECT = {'none': False, 'full': True}

def export(dst):
    if BASELINE:
        tar = subprocess.run(['git', '-C', REPO, 'archive', BASE_REF] + PATHS,
                             capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', dst], input=tar, check=True)
    else:
        for p in PATHS:
            s, d = os.path.join(REPO, p), os.path.join(dst, p)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, d)


def parse_reg(path):
    """Wine .reg hive -> {lower key: {lower value name ('' = default): data}}."""
    keys, cur = {}, None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = re.match(r'^\[(.*)\] \d+', line)
        if m:
            cur = keys.setdefault(m.group(1).replace('\\\\', '\\').lower(), {})
            continue
        m = cur is not None and re.match(r'^(@|"(?:[^"\\]|\\.)*")=(?:str\(\d\):)?"((?:[^"\\]|\\.)*)"', line)
        if m:
            cur['' if m.group(1) == '@' else m.group(1)[1:-1].lower()] = m.group(2).replace('\\\\', '\\')
    return keys


def main():
    if not shutil.which('docker'):
        print('CANNOT RUN: docker not found'); return 2
    work = tempfile.mkdtemp(prefix='rd1004-', dir=os.environ.get('RD_TMP'))
    try:
        os.makedirs(os.path.join(work, 'src'))
        export(os.path.join(work, 'src'))
        open(os.path.join(work, 'zz_harness.iss'), 'w').write(HARNESS)
        open(os.path.join(work, 'run.sh'), 'w').write(CONTAINER)
        open(os.path.join(work, 'root.sh'), 'w').write(ROOT_WRAP)
        print('%s: installer from %s (%s), running under Wine...' %
              ('BASELINE' if BASELINE else 'FIX', REPO, BASE_REF if BASELINE else 'working tree'), flush=True)
        r = subprocess.run(['docker', 'run', '--rm', '--platform', 'linux/amd64', '--user', 'root',
                            '-v', work + ':/work', '--entrypoint', 'sh', IMAGE, '/work/root.sh'], capture_output=True, text=True)
        if 'XVFB-INSTALL-FAILED' in r.stdout:
            print('CANNOT RUN: could not apt-get install xvfb in the container'); return 2
        if 'COMPILE-FAILED' in r.stdout:
            print('CANNOT RUN: ISCC failed:\n' + open(os.path.join(work, 'iscc.log'), errors='replace').read()[-2000:])
            return 2
        failures = 0
        for sc, want in EXPECT.items():
            d = os.path.join(work, 'reg', sc)
            log = open(os.path.join(d, 'setup.log'), encoding='utf-8-sig', errors='replace').read() \
                if os.path.exists(os.path.join(d, 'setup.log')) else ''
            if 'Installation process succeeded' not in log or 'Windows version: 10.0' not in log:
                print('CANNOT RUN: scenario %s did not install on "Windows 10" (see setup.log)' % sc)
                return 2
            hklm = parse_reg(os.path.join(d, 'system.reg'))
            caps = hklm.get(CAPS, {})
            if not caps:
                print('CANNOT RUN: no %s key at all in scenario %s' % (CAPS, sc))
                return 2
            for ext, progid in sorted(OURS.items()):
                cap = caps.get('.' + ext)
                cmd = hklm.get('software\\classes\\%s\\shell\\open\\command' % progid.lower(), {}).get('')
                lm = hklm.get('software\\classes\\.' + ext, {}).get('')
                ok_cap, ok_cmd = cap == progid, bool(cmd) and '%1' in cmd
                ok_assoc = (lm == progid) == want
                if not (ok_cap and ok_cmd and ok_assoc):
                    failures += 1
                print('  %-4s .%-4s DefaultApps(Capabilities)=%-16s open=%-3s HKLM .%s=%-16s %s' %
                      (sc, ext, cap, 'yes' if ok_cmd else 'no', ext, lm,
                       'ok' if ok_cap and ok_cmd and ok_assoc else 'FAILED'))
        print('PASS' if not failures else 'FAIL (%d)' % failures)
        return 0 if not failures else 1
    finally:
        if os.environ.get('RD_KEEP'):
            print('kept', work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
