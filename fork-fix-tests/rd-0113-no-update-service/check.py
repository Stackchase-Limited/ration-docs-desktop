#!/usr/bin/env python3
"""RD-0113: the Windows installers no longer install ONLYOFFICE's update service.

Ration Docs has no update module, yet the Inno installer ran `updatesvc.exe --install`
on every install (an auto-start Windows service the app never talks to), and the MSI
project carried an UpdateService feature that installed it when UPDATE_SERVICE=1.

Static check of the installer sources:
  Inno: no `--install` call; updatesvc.exe excluded from [Files]; [InstallDelete] removes
        it; PrepareToInstall and uninstall still run the old `--delete` (upgrades clean up).
  MSI:  no updatesvc component, file, feature, ServiceInstall or ServiceControl rows.

  ./check.py                       working tree, must PASS
  BASELINE=1 ./check.py            parent of the fix (BASE_REF), must FAIL
  RD_REPO=<desktop-apps checkout>  default ../../desktop-apps
"""
import os, re, subprocess, sys
repo = os.environ.get('RD_REPO') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../desktop-apps')
base = os.environ.get('BASE_REF', 'ebfd5ebef')

def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.check_output(['git', '-C', repo, 'show', f'{base}:{rel}']).decode('utf-8')
    return open(os.path.join(repo, rel), 'rb').read().decode('utf-8')

code, common, aip = read('package/inno/_code.iss'), read('package/inno/common.iss'), read('package/advinst/DesktopEditors.aip')
checks = [
    ('Inno: no updatesvc --install', not re.search(r"updatesvc\.exe'\),\s*'--install", code)),
    ('Inno: old service still deleted before install and on uninstall', len(re.findall(r"updatesvc\.exe'\),\s*'--delete'", code)) >= 2),
    ('Inno: payload wildcards exclude updatesvc.exe', all('Excludes: "\\updatesvc.exe"' in l
        for l in common.splitlines() if l.startswith('Source: "{#BUILD_DIR}\\desktop\\*') and '*.dll' not in l)),
    ('Inno: [InstallDelete] removes updatesvc.exe', 'Type: files; Name: {app}\\updatesvc.exe' in common),
    ('MSI: no updatesvc rows', not re.search(r'updatesvc|Feature="UpdateService"|Feature_="UpdateService"|<ROW ServiceInstall|<ROW ServiceControl', aip)),
]
ok = True
for name, good in checks:
    print(('ok   ' if good else 'FAIL ') + name); ok &= good
print('PASS RD-0113' if ok else 'FAIL RD-0113'); sys.exit(0 if ok else 1)
