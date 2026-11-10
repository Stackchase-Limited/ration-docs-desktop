#!/usr/bin/env python3
r"""
#2031 - the Windows (Inno Setup) installer associated .docx, .pptx, .xlsx and
.pdf with Ration Docs even when the user unticked them on the association page
(or chose "Don't associate", or ran a silent install without /FULLASSOCIATION),
and took .pdf from whatever application owned it.

Cause: DoPostInstall (package/inno/_code.iss) consults isAssociateExtension(i)
before writing HKLM\Software\Classes\.<ext> - but then always calls
AddContextMenuNewItems, whose Windows 10/11 branch (version.Major = 10) wrote
the default value of HKLM\Software\Classes\.docx/.pptx/.xlsx/.pdf to our ProgID
unconditionally (and HKCU's too, when HKCU had one). It does that so the
Explorer "New" menu entry (.<ext>\<ProgID>\ShellNew) shows, but the same value
is the file association. Fix: that write is now gated by the user's selection
(isAssociateExtensionByName -> isAssociateExtension). The ShellNew keys are
still written for every type.

How it is tested - the REAL installer, run under Wine:
  * the real package/inno/common.iss + _code.iss + defines.iss + _messages.iss
    (from RD_REPO, or `git show BASE_REF:` with BASELINE=1) are compiled by
    ISCC 6.7.1 under Wine (Docker image amake/innosetup, linux/amd64) with
    /D_RATION and a stub payload (a tiny exe/dll from Wine's system32);
  * each scenario installs that setup.exe /VERYSILENT into a fresh Wine prefix
    that reports Windows 10.0 and in which .pdf (HKLM + HKCU) and .xlsx (HKLM)
    already belong to another vendor; then Wine's registry hives are read back.
  * Scenarios: none (silent, no /FULLASSOCIATION = "Don't associate"),
    sel-odt-epub and sel-docx-pdf ("Associate selected" with only those
    ticked), full (/FULLASSOCIATION).
  The association page is a GUI page and does not exist in a silent install,
  so for the two sel-* scenarios a test-only wrapper (zz_harness.iss, below)
  #includes the real common.iss and, through an extra
  <event('CurStepChanged')> handler at ssInstall, builds ChlbAudio the way the
  page leaves it: radio 2 ("selected") checked and exactly the named
  extensions ticked. Everything else - isAssociateExtension, DoPostInstall,
  AddContextMenuNewItems - is the shipped code, compiled and executed.
  Two build-only edits are made to the COPY: LZMAUseSeparateProcess=no and
  Compression=zip (the LZMA worker process dies under Wine+qemu), and missing
  unofficial .isl/.islu translations are stubbed with Default.isl.

  ./extract_and_run.py             working tree, must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF (parent of the fix), must FAIL
  RD_REPO=<desktop-apps checkout>  default ../../desktop-apps
  RD_KEEP=1                        keep the temp dir (registry hives, setup logs)

What is NOT claimed: Wine is not Windows. Wine's GetVersion reports 10.0 here,
so the Windows 10/11 branch runs, but nothing about Explorer, the "New" menu,
UserChoice hashes or Default Apps is exercised; the `--assoc` hand-off to
RationDocs.exe goes to a stub. ARCH=x86 (the image's Wine prefix is 32-bit); the
association code has no arch branch. The MSI (package/advinst) is not covered.
Needs Docker and network (apt-get install xvfb inside the container); first run pulls amake/innosetup (~500 MB) and takes several
minutes on an arm64 Mac (amd64 emulation).
Exit 0 = pass, 1 = fail, 2 = could not run (no Docker / compile failed).
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
BASE_REF = os.environ.get('BASE_REF', 'fb27173cb^')
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
for sc in none sel-odt-epub sel-docx-pdf full; do
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

OURS = {'docx': 'RationDocs.Document.12', 'pptx': 'RationDocs.Show.12', 'xlsx': 'RationDocs.Sheet.12',
        'pdf': 'RationDocs.Pdf', 'odt': 'RationDocs.Document.2', 'epub': 'RationDocs.Epub',
        'doc': 'RationDocs.Document.1'}
PRIOR = {'pdf': 'OtherVendor.PdfDoc', 'xlsx': 'OtherVendor.Sheet'}

# scenario -> extensions that must be associated; every other OURS key must not be
EXPECT = {
    'none': set(),
    'sel-odt-epub': {'odt', 'epub'},
    'sel-docx-pdf': {'docx', 'pdf'},
    'full': set(OURS),
}


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
    work = tempfile.mkdtemp(prefix='rd2031-', dir=os.environ.get('RD_TMP'))
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
            hkcu = parse_reg(os.path.join(d, 'user.reg'))
            got = []
            for ext, progid in sorted(OURS.items()):
                lm = hklm.get('software\\classes\\.' + ext, {}).get('')
                cu = hkcu.get('software\\classes\\.' + ext, {}).get('')
                assoc = lm == progid or cu == progid
                ok = assoc == (ext in want)
                if ok and ext not in want and ext in PRIOR:
                    ok = lm == PRIOR[ext] and (ext != 'pdf' or cu == PRIOR[ext])
                got.append('.%s=%s%s' % (ext, lm, '' if cu is None else '/HKCU:' + cu))
                if not ok:
                    failures += 1
                    print('  FAIL %-13s .%-4s HKLM=%s HKCU=%s (expected %s)' %
                          (sc, ext, lm, cu, 'associated' if ext in want else
                           PRIOR.get(ext, 'not ours') + ' kept'))
            # the Explorer "New" entries are still installed for every type
            for ext in ('docx', 'pptx', 'xlsx', 'pdf'):
                k = 'software\\classes\\.%s\\%s\\shellnew' % (ext, OURS[ext].lower())
                if 'filename' not in hklm.get(k, {}):
                    failures += 1
                    print('  FAIL %-13s ShellNew for .%s missing' % (sc, ext))
            print('%-13s %s' % (sc, ' '.join(got)))
        print('PASS' if not failures else 'FAIL (%d)' % failures)
        return 0 if not failures else 1
    finally:
        if os.environ.get('RD_KEEP'):
            print('kept', work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
