#!/bin/sh
# ONLYOFFICE/DesktopEditors#139 - "Some unicode characters make content disappear
# after save/close/open".
#
# NSBinPptxRW::CXmlWriter::WriteStringXML is the escaper for <a:t> run text - the
# text of every run on every slide. It escaped the five predefined entities and
# nothing else, so a character that XML 1.0 forbids outright (U+0008 and U+001C
# in the report, and the rest of the C0 controls, U+FFFE/U+FFFF and unpaired
# surrogates with them) went into ppt/slides/slideN.xml raw. That part is then
# not well-formed, our own reader fails it whole, and the slide comes back empty
# on reopen - every run on it, not just the offending character.
#
# The fix routes the text through XmlUtils::EncodeXmlString, the same helper the
# DOCX run-text writer and the cNvPr attributes in this same writer already use.
#
# This extracts the real WriteStringXML - and the real EncodeXmlString,
# IsUnicodeSymbol and replace_all it may call - by brace matching, and checks
# both halves of the contract: nothing illegal in the output, and nothing legal
# lost from it.
#
#   ./run.sh              current working tree, must PASS
#   BASELINE=1 ./run.sh   the same test against git HEAD, must FAIL
set -e
cd "$(dirname "$0")"
python3 ./extract.py > harness.cpp
clang++ -std=c++14 -Wall -o harness harness.cpp
set +e
./harness
rc=$?
set -e
rm -f harness harness.cpp
exit $rc
