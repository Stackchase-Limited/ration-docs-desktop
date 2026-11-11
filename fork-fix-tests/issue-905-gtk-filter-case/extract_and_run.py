#!/usr/bin/env python3
"""
#905 (thread, vemonet 2023) - on Linux, Insert > Image > From file opens with the
"All Images" filter selected and does not show "Photo.JPG": "it automatically
filter for 'All images', which ignores .JPG files, so we need to change the
filter for 'All files' every time".

Cause: win-linux/src/platform_linux/gtkfilechooser.cpp nativeFileDialog() turns
each "*.jpg" of the filter string into gtk_file_filter_add_pattern(filter, "*.jpg").
GTK 3 matches those patterns case-sensitively (checked: GTK 3.24.41 on Ubuntu
24.04 and Homebrew GTK 3.24.51 hide Photo.JPG and x.Jpg), and cameras and phones
write upper-case extensions. Fix: each pattern is added case-insensitively as a
bracket glob ("*.[jJ][pP][gG]").

This slices the REAL "// Filters" block out of nativeFileDialog (brace matching),
plus the real parseString() and, when present, caseInsensitivePattern(), and runs
it with real GTK 3 against a stub chooser that just collects the GtkFileFilters it
is given. It then asks each filter (gtk_file_filter_filter) whether it shows a
set of file names. The filter string is the one cfiledialog.cpp builds for
Insert Image (CFileDialogWrapper::modalOpenImage - hard-coded here as input).

Claimed: "All Images" and "Jpeg" show photo.jpg, Photo.JPG and x.Jpg, still hide
notes.txt; filter names and the selected filter are unchanged.
NOT claimed: the XDG portal dialog (xdgdesktopportal.cpp, used when the GTK
dialog is not) - its glob patterns are also matched by the portal backend, but
the selected pattern comes back and is used as the save extension, so it is left
alone; the Qt (non-native) dialog; a GUI run.

  python3 fork-fix-tests/issue-905-gtk-filter-case/extract_and_run.py
  RD_REPO=<desktop-apps checkout>  (default ../../desktop-apps)
  BASELINE=1                       reads the source from BASE_REF; must FAIL.
Needs GTK 3 dev files (pkg-config gtk+-3.0; on macOS Homebrew gtk+3 is found
automatically).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', 'eea379f8a^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'win-linux/src/platform_linux/gtkfilechooser.cpp'

src = (subprocess.check_output(['git', '-C', REPO, 'show', BASE_REF + ':' + REL]).decode()
       if BASELINE else open(os.path.join(REPO, REL), encoding='utf-8').read())


def braces(s, start):
    o = s.index('{', start)
    d = 0
    for i in range(o, len(s)):
        if s[i] == '{':
            d += 1
        elif s[i] == '}':
            d -= 1
            if d == 0:
                return s[start:i + 1]
    raise SystemExit('unbalanced braces')


parse = braces(src, src.index('static GSList* parseString('))
helper = ''
if 'static std::string caseInsensitivePattern(' in src:
    helper = braces(src, src.index('static std::string caseInsensitivePattern('))
fn = braces(src, src.index('static void nativeFileDialog('))
at = fn.index('// Filters')
block = braces(fn, fn.index('if (mode != Gtk::Mode::FOLDER', at))
assert 'gtk_file_filter_add_pattern' in block and 'gtk_file_chooser_add_filter' in block, 'sliced the wrong block'

IMAGE_FILTER = ('All Images (*.jpeg *.jpg *.png *.gif *.bmp *.tiff *.tif *.heif *.heic *.svg)'
                ';;Jpeg (*.jpeg *.jpg);;Png (*.png);;Gif (*.gif);;Bmp (*.bmp);;Tiff (*.tiff *.tif);;Heif (*.heif *.heic)')
NAMES = ['photo.jpg', 'Photo.JPG', 'x.Jpg', 'scan.PNG', 'notes.txt']

prog = r'''
#include <gtk/gtk.h>
#include <string>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
namespace Gtk { typedef enum { OPEN = 0, SAVE = 1, FOLDER = 2 } Mode; }
static GSList* g_filters = NULL;
static GtkFileFilter* g_selected = NULL;
// the stub chooser: collect what the real block hands to GTK
#define gtk_file_chooser_add_filter(c, f) (g_filters = g_slist_append(g_filters, (f)))
#define gtk_file_chooser_set_filter(c, f) (g_selected = (f))
''' + parse + '\n' + helper + r'''
int main(int argc, char** argv)
{
    Gtk::Mode mode = Gtk::Mode::OPEN;
    const char* flt = argv[1];
    char* sel = strdup(argv[2]);
    char** sel_filter = &sel;
    void* chooser = NULL;
    (void)chooser;
''' + block + r'''
    for (GSList* n = g_filters; n; n = n->next) {
        GtkFileFilter* f = (GtkFileFilter*)n->data;
        printf("%s%s|", gtk_file_filter_get_name(f), f == g_selected ? " [selected]" : "");
        for (int i = 3; i < argc; i++) {
            GtkFileFilterInfo info = {};
            info.contains = GTK_FILE_FILTER_DISPLAY_NAME;
            info.display_name = argv[i];
            printf("%s=%d ", argv[i], gtk_file_filter_filter(f, &info) ? 1 : 0);
        }
        printf("\n");
    }
    return 0;
}
'''

failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


tmp = tempfile.mkdtemp(prefix='rd905g-')
try:
    env = dict(os.environ)
    PKG_CONFIG = 'pkg-config'
    if sys.platform == 'darwin':
        try:
            brew = subprocess.check_output(['brew', '--prefix']).decode().strip()
            pfx = subprocess.check_output(['brew', '--prefix', 'gtk+3']).decode().strip()
            env['PKG_CONFIG_PATH'] = os.path.join(pfx, 'lib', 'pkgconfig') + ':' + env.get('PKG_CONFIG_PATH', '')
            PKG_CONFIG = os.path.join(brew, 'bin', 'pkg-config')  # Homebrew's, which knows its keg-only deps
        except Exception:
            pass
    flags = subprocess.check_output([PKG_CONFIG, '--cflags', '--libs', 'gtk+-3.0'], env=env).decode().split()
    with open(os.path.join(tmp, 't.cpp'), 'w') as f:
        f.write(prog)
    r = subprocess.run(['c++', '-std=c++17', '-w', os.path.join(tmp, 't.cpp'), '-o', os.path.join(tmp, 't')] + flags,
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        raise SystemExit('compile failed')
    out = subprocess.run([os.path.join(tmp, 't'), IMAGE_FILTER, 'All Images (*.jpeg *.jpg *.png *.gif *.bmp *.tiff *.tif *.heif *.heic *.svg)'] + NAMES,
                         capture_output=True, text=True, check=True).stdout
    rows = {}
    for line in out.strip().split('\n'):
        name, res = line.split('|')
        rows[name] = dict(kv.split('=') for kv in res.split())
    print(out.strip())

    allimg = rows.get('All Images (*.jpeg *.jpg *.png *.gif *.bmp *.tiff *.tif *.heif *.heic *.svg) [selected]')
    check('"All Images" is still the selected filter, names unchanged', allimg is not None and len(rows) == 7, str(list(rows)))
    if allimg:
        for n in ['photo.jpg', 'Photo.JPG', 'x.Jpg', 'scan.PNG']:
            check('All Images shows ' + n, allimg.get(n) == '1')
        check('All Images hides notes.txt', allimg.get('notes.txt') == '0')
    jpeg = rows.get('Jpeg (*.jpeg *.jpg)', {})
    check('Jpeg shows Photo.JPG', jpeg.get('Photo.JPG') == '1')
    check('Jpeg hides scan.PNG', jpeg.get('scan.PNG') == '0')
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
sys.exit(1 if failures else 0)
