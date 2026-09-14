#!/bin/sh
# #2274 - the payload shipped a Qt plugin whose Qt libraries it does not ship.
#
# qt_copy_plugin copies a plugin directory wholesale, while the Qt libraries are an
# explicit list in deploy_desktop.py. libqtvirtualkeyboardplugin needs QtQml,
# QtQmlModels, QtQuick and QtVirtualKeyboard - checked against our own Qt, none of
# them is on that list. It therefore cannot load from the bundle at all; and on a
# machine that does have system Qt5 the loader satisfies those from the system,
# they link the system QtCore, and the process holds two QtCores - the #1748 shape.
#
# The fix ships the stack rather than dropping the plugin: Qt5Qml, Qt5QmlModels,
# Qt5Quick and Qt5VirtualKeyboard, plus the qml/ import trees those imports actually
# resolve against, with main.cpp pointing QML2_IMPORT_PATH at them. Roughly 25MB.
#
# This test guards the class rather than that one plugin. The macOS app here is Cocoa,
# not Qt, so there is no real Qt payload on this host to check against; it builds the
# same shape for real instead - a plugin linked against two frameworks, one shipped and
# one not - and checks that check_symbol_closure.py names the missing one and stays
# quiet about the present one. That is what would have caught #2274 at package time,
# and what will catch the next plugin copied in wholesale.
set -e
cd "$(dirname "$0")"
CHECK=../../build_tools/scripts/check_symbol_closure.py

rm -rf payload-bad payload-good
mkdir -p payload-bad/QtCore.framework/Versions/A payload-good/QtCore.framework/Versions/A
mkdir -p payload-good/QtQuick.framework/Versions/A

mk() { # dir name src
  clang++ -dynamiclib -install_name "@rpath/$2.framework/Versions/A/$2" \
          -o "$1/$2.framework/Versions/A/$2" "$3"
}
mk payload-bad  QtCore  qtcore.cpp
mk payload-good QtCore  qtcore.cpp
mk payload-good QtQuick qtquick.cpp
clang++ -dynamiclib -o /tmp/_qtquick_ref.dylib \
        -install_name "@rpath/QtQuick.framework/Versions/A/QtQuick" qtquick.cpp

for d in payload-bad payload-good; do
  clang++ -dynamiclib -o "$d/libplugin.dylib" plugin.cpp \
          "$d/QtCore.framework/Versions/A/QtCore" /tmp/_qtquick_ref.dylib
done

echo "--- the plugin's Qt dependencies ---"
otool -L payload-bad/libplugin.dylib | grep -oE "Qt[A-Za-z]+" | sort -u | sed 's/^/    /'

echo
echo "--- payload missing QtQuick: the check must name it ---"
if python3 "$CHECK" payload-bad; then
  echo "FAIL: the checker passed a payload missing a Qt library it needs" >&2
  exit 1
fi

echo
echo "--- payload with both: the check must be quiet ---"
python3 "$CHECK" payload-good

rm -f /tmp/_qtquick_ref.dylib
echo
echo "ok - a Qt dependency the payload does not ship is reported; one it ships is not"
