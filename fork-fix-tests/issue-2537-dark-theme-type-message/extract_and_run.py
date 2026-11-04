#!/usr/bin/env python3
"""
#2537 (follow-up) - with the app theme "Dark" (theme-night) or "Same as system"
on a dark OS, the Qt message box is the plain light Qt default.

Cause.  After c946559b7 a dark system or app theme sends message boxes to the
themed Qt dialog (QtMsg, win-linux/src/components/cmessage.cpp), which styles
itself through res/styles/message.qss.  That file had dark rules only for
#messageBody[uitheme=theme-dark] and [uitheme=theme-contrast-dark], keyed on the
theme ID.  theme-night is also a dark theme - and it is THEME_DEFAULT_DARK_ID in
cthemes.cpp, i.e. what "Same as system" resolves to on a dark OS, the exact
setting of the #2537 report - so it matched nothing; so would any user theme of
type "dark" installed in uithemes/.

Fix.  QtMsg also sets the property uithemetype = GetCurrentTheme().stype()
("dark"/"light"), the mechanism styles.qss already uses for #mainPanel, and the
generic dark rules in message.qss are keyed on [uithemetype=dark].  The
contrast-dark rules come later with the same selector shapes, so they still
override.

What this runs: the REAL property-setting lines of the QtMsg constructor
(extracted between setObjectName("messageBody") and the first layout) and the
REAL message.qss, in a real QApplication (Homebrew qt@5, offscreen platform,
Fusion style as main.cpp sets).  GetCurrentTheme() is a stub that returns the id
and type read from each REAL res/styles/theme-*.json, plus one synthetic user
theme of type dark.  The dialog body is rendered with grab() and pixels are
sampled: every dark-type theme must get a dark body and a dark button with light
label text, every light theme must stay light.  Baseline (BASELINE=1, sources
from BASE_REF): theme-night and the user dark theme MUST FAIL.

NOT claimed: no Windows/Linux build of the app and no screenshot of the real
dialog; colours for theme-night are the theme-dark ones (not a new palette).
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '10b49fdd23^')
BASELINE = bool(os.environ.get('BASELINE'))
CPP_PATH = 'win-linux/src/components/cmessage.cpp'
QSS_PATH = 'win-linux/res/styles/message.qss'
QT = os.environ.get('QT_DIR', '/opt/homebrew/opt/qt@5')


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


src = read(CPP_PATH)
a = src.find('    m_centralWidget->setObjectName("messageBody");')
b = src.find('    QVBoxLayout * _c_layout', a)
if a < 0 or b < 0:
    raise SystemExit('QtMsg constructor not recognised - the extractor needs updating')
props = src[a:b]
if 'setProperty("uitheme"' not in props:
    raise SystemExit('QtMsg no longer sets uitheme where expected - revisit this test')

out = tempfile.mkdtemp(prefix='rd2537b_')
qss = os.path.join(out, 'message.qss')
with open(qss, 'w', encoding='utf-8') as f:
    f.write(read(QSS_PATH))

themes = []
for p in sorted(glob.glob(os.path.join(REPO, 'win-linux', 'res', 'styles', 'theme-*.json'))):
    j = json.load(open(p, encoding='utf-8'))
    themes.append((j['id'], j['type']))
if not any(t == 'dark' for _, t in themes):
    raise SystemExit('no dark theme json found under %s' % REPO)
themes.append(('theme-user-midnight', 'dark'))      # a user theme dropped into uithemes/

cases = '\n'.join('    run(L"%s", "%s");' % t for t in themes)

PROGRAM = r'''
#include <QApplication>
#include <QFile>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QPushButton>
#include <QStyleFactory>
#include <QWidget>
#include <cstdio>
#include <string>

struct ThemeStub {
    std::wstring id; QString type;
    std::wstring originalId() const { return id; }
    QString stype() const { return type; }
};
static ThemeStub g_theme;
#define GetCurrentTheme() g_theme

struct QtMsgHarness {
    QWidget *m_centralWidget;
    explicit QtMsgHarness(QWidget *w) : m_centralWidget(w) {
%(props)s
    }
};

static QString g_qss;
static int failures = 0;
static double lum(QRgb c) { return (0.2126*qRed(c) + 0.7152*qGreen(c) + 0.0722*qBlue(c)) / 255.0; }

static void run(const wchar_t *id, const char *type)
{
    g_theme = ThemeStub{id, QString::fromLatin1(type)};
    QWidget body;
    QtMsgHarness h(&body);
    auto *lay = new QHBoxLayout(&body);
    auto *label = new QLabel("More than one document is open.");
    auto *button = new QPushButton("Yes");
    lay->addWidget(label); lay->addWidget(button);
    body.setStyleSheet(g_qss);
    body.resize(320, 60);
    body.show();
    QApplication::processEvents();
    QImage img = body.grab().toImage();
    double bg  = lum(img.pixel(1, 1));
    QPoint bc = button->geometry().center();
    double btn = lum(img.pixel(bc.x(), button->geometry().top() + 3));
    double txt = lum(label->palette().color(QPalette::WindowText).rgb());
    bool dark = std::string(type) == "dark";
    bool ok = dark ? (bg < 0.35 && btn < 0.45 && txt > 0.6) : (bg > 0.7 && txt < 0.4);
    printf("  %%-22s %%-5s body %%.2f  button %%.2f  text %%.2f  %%s\n",
           QString::fromWCharArray(id).toLatin1().constData(), type, bg, btn, txt, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    app.setStyle(QStyleFactory::create("Fusion"));
    QFile f(argv[1]); f.open(QIODevice::ReadOnly | QIODevice::Text);
    g_qss = QString::fromUtf8(f.readAll());
%(cases)s
    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

prog = PROGRAM % {'props': props, 'cases': cases}
cpp = os.path.join(out, 'main.cpp')
with open(cpp, 'w', encoding='utf-8') as f:
    f.write(prog)
binp = os.path.join(out, 'run')
fw = os.path.join(QT, 'lib')
inc = ['-I' + os.path.join(fw, m + '.framework', 'Headers') for m in ('QtCore', 'QtGui', 'QtWidgets')]
cc = subprocess.run(['c++', '-std=c++17', '-F' + fw] + inc + ['-o', binp, cpp,
                     '-framework', 'QtCore', '-framework', 'QtGui', '-framework', 'QtWidgets',
                     '-Wl,-rpath,' + fw], capture_output=True, text=True)
if cc.returncode != 0:
    sys.stderr.write(cc.stdout + cc.stderr)
    sys.stderr.write('\ncompilation of the extracted source failed: %s\n' % cpp)
    raise SystemExit(2)
env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
           QT_QPA_PLATFORM_PLUGIN_PATH=os.path.join(QT, 'plugins', 'platforms'))
print('revision under test: %s' % ('BASELINE ' + BASE_REF if BASELINE else REPO), flush=True)
r = subprocess.run([binp, qss], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
print(r.stdout, end='')
print('\n(extracted source: %s)' % cpp)
raise SystemExit(r.returncode)
