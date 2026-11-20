#!/usr/bin/env python3
"""
Upstream 86a717a42f (bug 82231) + 7a9c80e60c (bug 83065), backported for 2026.3.1:
docbuilder / doctrenderer scripts could read and write files they should not.

  86a717a42f  With the builder in server mode (--save-use-only-names, how the document server
              runs it), native.GetFileBinary only checked that the path STARTED with the
              document's folder, so "<folder>/../../../<anything>" passed, and
              native.GetFontBinary returned any existing absolute path. Fix: the path is
              normalised and must lie inside the folder / be a known font.
  7a9c80e60c  The params string of builder.OpenFile / builder.SaveFile was pasted into x2t's
              task XML as is, so <m_sFileTo>/<m_sFileFrom>/<m_sTempDir> in it redirected x2t:
              SaveFile wrote wherever the script said. Fix: those elements are removed.
              (Our hand-merge also keeps the old ' -> &quot; replacement working.)

What runs (end to end, REAL code): the docbuilder binary with the doctrenderer/kernel/...
frameworks and x2t under test, the 2026.3.0 editors' sdkjs, and a script that
  - reads a "secret" file outside the work folder with native.GetFileBinary("<folder>/../..")
    and native.GetFontBinary("<abs path>") in server mode,
  - saves with SaveFile("txt", <ok path>, "<m_sFileTo>EVIL</m_sFileTo>"),
  - saves a second time with params using '...' quotes in m_sJsonParams (the replacement
    our tree has always done), which must still save.
Passes when both reads come back null, nothing is written at EVIL, the ok file exists and
the quoted-params save works. BASELINE (the 2026.3.0 frameworks and x2t) reads the secret
and writes EVIL.

  RD_CORE=<core checkout>   (default ../../core): docbuilder from <core>/build/bin/mac_arm64,
                            frameworks from RD_CORE_LIBS (default <core>/build/lib/mac_arm64),
                            x2t from RD_X2T (default <core>/build/bin/mac_arm64/x2t)
  BASELINE=1                frameworks + x2t from RD_PAYLOAD_BASE; must FAIL
  RD_PAYLOAD_BASE           default .rd-work/mac-2026.3.0/payload (v2026.3.0 = aa16ec2c0d);
                            also supplies sdkjs, web-apps' xregexp and the empty templates
  RD_FONTS                  font cache (default .rd-work/fonts-cache; copied first)
Exit 77 (skip) without docbuilder, payload or fonts.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
CORE = os.environ.get('RD_CORE') or os.path.join(ROOT, 'core')
RDWORK = os.path.normpath(os.path.join(ROOT, '..', '.rd-work'))
BASELINE = bool(os.environ.get('BASELINE'))
PAYLOAD = os.environ.get('RD_PAYLOAD_BASE') or os.path.join(RDWORK, 'mac-2026.3.0', 'payload')
FONTS = os.environ.get('RD_FONTS') or os.path.join(RDWORK, 'fonts-cache')
DOCBUILDER = os.path.join(CORE, 'build', 'bin', 'mac_arm64', 'docbuilder')
if BASELINE:
    LIBS, X2T = os.path.join(PAYLOAD, 'converter'), os.path.join(PAYLOAD, 'converter', 'x2t')
else:
    LIBS = os.environ.get('RD_CORE_LIBS') or os.path.join(CORE, 'build', 'lib', 'mac_arm64')
    X2T = os.environ.get('RD_X2T') or os.path.join(CORE, 'build', 'bin', 'mac_arm64', 'x2t')

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def setup(work):
    """work/bin: docbuilder + x2t + DoctRenderer.config + empty/; work/Frameworks: links (both binaries use @executable_path/../Frameworks)."""
    b = os.path.join(work, 'bin')
    os.makedirs(os.path.join(b, 'empty'))
    os.makedirs(os.path.join(work, 'Frameworks'))
    for f in glob.glob(os.path.join(LIBS, '*.framework')):
        os.symlink(f, os.path.join(work, 'Frameworks', os.path.basename(f)))
    shutil.copy(DOCBUILDER, b)
    shutil.copy(X2T, os.path.join(b, 'x2t'))
    for f in glob.glob(os.path.join(PAYLOAD, 'converter', 'empty', 'en-US', 'new.*')):
        shutil.copy(f, os.path.join(b, 'empty'))
    fonts = os.path.join(work, 'fonts')
    shutil.copytree(FONTS, fonts)
    ed = os.path.join(PAYLOAD, 'editors')
    open(os.path.join(b, 'DoctRenderer.config'), 'w').write(
        '<Settings><file>{e}/sdkjs/common/Native/native.js</file><file>{e}/sdkjs/common/Native/jquery_native.js</file>'
        '<allfonts>{f}/AllFonts.js</allfonts><file>{e}/web-apps/vendor/xregexp/xregexp-all-min.js</file>'
        '<sdkjs>{e}/sdkjs</sdkjs></Settings>'.format(e=ed, f=fonts))
    return b, fonts


def run(b, fonts, script, *args):
    p = os.path.join(b, 'script.docbuilder')
    open(p, 'w').write(script)
    env = dict(os.environ, DYLD_FRAMEWORK_PATH=os.path.join(os.path.dirname(b), 'Frameworks'))
    r = subprocess.run([os.path.join(b, 'docbuilder'), '--check-fonts=0', '--all-fonts-path=' + os.path.join(fonts, 'AllFonts.js')]
                       + list(args) + [p], capture_output=True, text=True, timeout=300, env=env, cwd=b)
    return r


def text(p):
    return open(p, encoding='utf-8-sig').read().strip() if os.path.exists(p) else None


def main():
    for p, what in ((DOCBUILDER, 'docbuilder'), (X2T, 'x2t'), (os.path.join(LIBS, 'doctrenderer.framework'), 'doctrenderer.framework'),
                    (os.path.join(PAYLOAD, 'editors', 'sdkjs', 'word'), 'sdkjs'), (os.path.join(FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('%s: frameworks %s' % ('BASELINE' if BASELINE else 'under test', LIBS))
    work = tempfile.mkdtemp(prefix='up86a717-')
    try:
        b, fonts = setup(work)
        secret = os.path.join(work, 'secret.txt')
        open(secret, 'w').write('TOP SECRET 0123456789')
        out = os.path.join(work, 'out')
        os.makedirs(out)
        evil = os.path.join(work, 'evil.txt')
        ok = os.path.join(out, 'ok.txt')
        up = '/..' * 40
        script = '''builder.CreateFile("docx");
var p = native.GetFilePath();
var dir = p.substring(0, p.lastIndexOf("/"));
var r1 = native.GetFileBinary(dir + "%(up)s%(secret)s");
var r2 = native.GetFontBinary("%(secret)s");
Api.GetDocument().GetElement(0).AddText("FILE=" + (r1 ? r1.length : "null") + " FONT=" + (r2 ? r2.length : "null"));
builder.SaveFile("txt", "%(ok)s", "<m_sFileTo>%(evil)s</m_sFileTo>");
builder.CloseFile();
''' % dict(up=up, secret=secret, ok=ok, evil=evil)
        r = run(b, fonts, script, '--save-use-only-names=' + out)
        got = text(ok)
        print('server mode: rc=%d ok.txt=%r evil.txt=%r' % (r.returncode, got, text(evil)))
        if r.returncode:
            print(r.stderr[-800:])
        check(got is not None, 'SaveFile wrote the file the builder asked for')
        check(got is not None and 'FILE=null' in got, 'native.GetFileBinary("<doc folder>/../..<secret>") is refused')
        check(got is not None and 'FONT=null' in got, 'native.GetFontBinary("<secret, not a font>") is refused')
        check(not os.path.exists(evil), 'SaveFile params cannot redirect x2t\'s m_sFileTo (server mode)')

        # local (non-server) builder: the params filter applies here too; ' quotes still become &quot;
        ok2, evil2 = os.path.join(out, 'local.txt'), os.path.join(work, 'evil2.txt')
        q = os.path.join(out, 'quoted.txt')
        script = '''builder.CreateFile("docx");
Api.GetDocument().GetElement(0).AddText("local");
builder.SaveFile("txt", "%(ok)s", "<m_sFileTo>%(evil)s</m_sFileTo>");
builder.SaveFile("txt", "%(q)s", "<m_sJsonParams>{'a':1}</m_sJsonParams>");
builder.CloseFile();
''' % dict(ok=ok2, evil=evil2, q=q)
        r = run(b, fonts, script)
        if r.returncode:
            print('  (docbuilder rc=%d; stderr tail: %r)' % (r.returncode, r.stderr[-300:]))
        print('local mode: rc=%d local.txt=%r quoted.txt=%r evil2.txt=%r' % (r.returncode, text(ok2), text(q), text(evil2)))
        check(text(ok2) == 'local', 'local builder: SaveFile wrote the file the builder asked for')
        check(not os.path.exists(evil2), 'local builder: SaveFile params cannot redirect x2t\'s m_sFileTo')
        check(r.returncode == 0 and text(q) == 'local', "local builder: params written with ' quotes still save (rc=%d)" % r.returncode)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: upstream 86a717a42f/7a9c80e60c builder scripts stay inside their files')


if __name__ == '__main__':
    main()
