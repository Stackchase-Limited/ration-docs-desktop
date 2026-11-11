#!/usr/bin/env python3
"""
#1664 (security follow-up) - the build must not bundle plugin API scripts it
downloads at build time.

Bug: build_tools' deploys (deploy_desktop.py, deploy_server.py,
develop/config_server.py, and base.support_old_versions_plugins) downloaded
v1/plugins.js, plugins-ui.js and plugins.css from
https://onlyoffice.github.io/sdkjs-plugins/v1/ at every build and shipped
whatever came back. Every bundled plugin and the plugin store load them into
file:// pages that get the desktop bridge, so whoever controlled that host (or
the build machine's network path to it) at build time put code into the app,
and two builds of the same commit could ship different code.

Fix (build_tools a3a1931, "Windows pass ... plugin API from our tree", on
lab02 ration/9.4-stability since 2026-10-22): the three files are checked in
under vendor/sdkjs-plugins/v1 (from onlyoffice.github.io at the commit the
9.4 lock pins) and base.copy_plugins_api() copies them; no deploy downloads
them any more.

This test
  1. parses every build_tools script (ast) and fails on any download(...) call
     whose URL mentions sdkjs-plugins;
  2. imports the REAL base.py of the tree under test with base.download()
     replaced by a function that fails, runs the real copy_plugins_api() and
     support_old_versions_plugins() into a temp dir, and checks that they
     produce plugins.js/plugins-ui.js/plugins.css and pluginBase.js offline;
  3. checks the produced files are byte-identical (sha256) to
     sdkjs-plugins/v1 in onlyoffice.github.io at the commit pinned in
     locks/onlyoffice-desktop-9.4.0.lock (the pinned, reviewed source).

NOT claimed: the production build server's own config (not in the repo:
whether it sets desktop-marketplace="1", which since a3a1931 decides whether
the plugin store ships at all; MACOS_ARM64_DESKTOP_BUILD.md requires
update="0", without which make.py would check out ONLYOFFICE's
onlyoffice.github.io instead of ours); the desktop app itself still fetches
v1/plugins*.js from onlyoffice.github.io at RUN time when the user installs a
plugin from the store (desktop-sdk client_renderer_wrapper.cpp, "ENGINE can be
updated") - not a build step, reported separately.

Env: RD_REPO   build_tools checkout (default ../../build_tools). NOTE: it must
               be at or after lab02 ration/9.4-stability a3a1931.
     RD_GHIO   onlyoffice.github.io checkout (default ../../onlyoffice.github.io)
     BASELINE=1 uses the tree at BASE_REF (git archive); must FAIL.
"""
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import warnings

# upstream build scripts have old-style regex escapes; not this test's business
warnings.simplefilter("ignore", SyntaxWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get("RD_REPO") or os.path.join(HERE, "..", "..", "build_tools"))
GHIO = os.path.abspath(os.environ.get("RD_GHIO") or os.path.join(HERE, "..", "..", "onlyoffice.github.io"))
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get("BASE_REF") or "a3a1931^"
BASELINE = bool(os.environ.get("BASELINE"))
API = ("plugins.js", "plugins-ui.js", "plugins.css")

failures = 0


def check(name, ok, detail=""):
    global failures
    if ok:
        print("ok   " + name)
    else:
        failures += 1
        print("FAIL " + name + (": " + detail if detail else ""))


def sha(data):
    return hashlib.sha256(data).hexdigest()


tmp = tempfile.mkdtemp(prefix="rd-1664-build-")
try:
    if BASELINE:
        tree = os.path.join(tmp, "tree")
        os.mkdir(tree)
        archive = subprocess.run(["git", "-C", REPO, "archive", BASE_REF, "scripts", "vendor", "locks"],
                                 check=False, capture_output=True)
        if archive.returncode != 0:  # vendor/ does not exist before the fix
            archive = subprocess.run(["git", "-C", REPO, "archive", BASE_REF, "scripts", "locks"],
                                     check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", tree], input=archive.stdout, check=True)
    else:
        tree = REPO

    # 1. no build script downloads the plugin API
    downloads = []
    for root, dirs, files in os.walk(os.path.join(tree, "scripts")):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            with open(p, encoding="utf-8", errors="replace") as fh:
                try:
                    mod = ast.parse(fh.read())
                except SyntaxError:
                    continue
            for node in ast.walk(mod):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name != "download":
                    continue
                texts = [c.value for a in node.args for c in ast.walk(a)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str)]
                if any("sdkjs-plugins" in t for t in texts):
                    downloads.append("%s:%d %s" % (os.path.relpath(p, tree), node.lineno, texts[0]))
    check("no build script downloads sdkjs-plugins/v1", not downloads, "; ".join(downloads))

    # 2. the real copy functions work offline
    out = os.path.join(tmp, "out")
    runner = r'''
import sys, os
sys.path.insert(0, sys.argv[1])
import base
def no_network(url, path):
    raise SystemExit("base.download(%s) called" % url)
base.download = no_network
out = sys.argv[2]
if not hasattr(base, "copy_plugins_api"):
    raise SystemExit("base.copy_plugins_api missing")
base.copy_plugins_api(out + "/v1")
os.makedirs(out + "/old")
base.support_old_versions_plugins(out + "/old")
'''
    run = subprocess.run([sys.executable, "-I", "-W", "ignore", "-c", runner, os.path.join(tree, "scripts"), out],
                         capture_output=True, text=True)
    produced = run.returncode == 0 and all(os.path.isfile(os.path.join(out, "v1", n)) for n in API) \
        and os.path.isfile(os.path.join(out, "old", "pluginBase.js"))
    check("copy_plugins_api / support_old_versions_plugins work with no network", produced,
          (run.stderr.strip().splitlines() or ["no output"])[-1])

    # 3. ... and give the pinned upstream bytes
    lock = os.path.join(tree, "locks", "onlyoffice-desktop-9.4.0.lock")
    commit = ""
    with open(lock, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "onlyoffice.github.io":
                commit = parts[1]
    pinned = {n: subprocess.run(["git", "-C", GHIO, "show", "%s:sdkjs-plugins/v1/%s" % (commit, n)],
                                capture_output=True, check=True).stdout for n in API}
    if produced:
        bad = [n for n in API if sha(open(os.path.join(out, "v1", n), "rb").read()) != sha(pinned[n])]
        base_js = open(os.path.join(out, "old", "pluginBase.js"), "rb").read()
        if base_js != pinned["plugins.js"] + b"\n\n" + pinned["plugins-ui.js"]:
            bad.append("pluginBase.js")
        check("plugin API matches onlyoffice.github.io %s (sha256)" % commit[:9], not bad, ", ".join(bad))
    else:
        check("plugin API matches onlyoffice.github.io %s (sha256)" % commit[:9], False, "nothing produced")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

label = " [BASELINE %s]" % BASE_REF if BASELINE else ""
if failures:
    print("FAIL #1664 build plugin API%s: %d check(s) failed" % (label, failures))
    sys.exit(1)
print("PASS #1664 build plugin API%s: the plugin API is copied from checked-in, pinned files" % label)
