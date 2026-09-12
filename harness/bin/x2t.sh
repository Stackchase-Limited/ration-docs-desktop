#!/bin/bash
# Convert a document with x2t, headlessly - no GUI, no editor.
#
#   harness/bin/x2t.sh in.xlsx out.csv
#   harness/bin/x2t.sh in.docx out.pdf
#   harness/bin/x2t.sh in.xlsx out.bin 8193      # explicit format id
#
# Useful for the file-format and converter bugs, where the question is what
# ends up in the output rather than what the UI did. Format ids come from
# core/Common/OfficeFileFormats.h.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

IN="${1:-}"
OUT="${2:-}"
FMT="${3:-}"
[ -n "$IN" ] && [ -n "$OUT" ] || { echo "usage: x2t.sh <in> <out> [formatId]" >&2; exit 2; }
[ -f "$IN" ] || { echo "x2t.sh: no such file: $IN" >&2; exit 1; }

CONV="$RD_APP/Contents/Resources/converter"
[ -x "$CONV/x2t" ] || { echo "x2t.sh: no x2t in $CONV" >&2; exit 1; }

# AVS_OFFICESTUDIO_FILE_* from core/Common/OfficeFileFormats.h
if [ -z "$FMT" ]; then
	case "${OUT##*.}" in
		docx) FMT=65   ;;  # DOCUMENT + 0x01
		odt)  FMT=67   ;;
		txt)  FMT=69   ;;
		rtf)  FMT=68   ;;
		pptx) FMT=129  ;;  # PRESENTATION + 0x01
		odp)  FMT=131  ;;
		xlsx) FMT=257  ;;  # SPREADSHEET + 0x01
		ods)  FMT=259  ;;
		csv)  FMT=260  ;;
		pdf)  FMT=513  ;;  # CROSSPLATFORM + 0x01
		bin)  FMT=8193 ;;  # CANVAS + 0x01 (the editors' internal format)
		*) echo "x2t.sh: unknown output type '${OUT##*.}' - pass a format id" >&2; exit 2 ;;
	esac
fi

FONTS="$(dirname "$(rd_settings_file)")/fonts"
PARAMS="$(mktemp -t rd-x2t).xml"
cat > "$PARAMS" <<XML
<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert>
<m_sFileFrom>$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN")</m_sFileFrom>
<m_sFileTo>$OUT</m_sFileTo>
<m_nFormatTo>$FMT</m_nFormatTo>
<m_sFontDir>$FONTS</m_sFontDir>
</TaskQueueDataConvert>
XML

set +e
( cd "$CONV" && DYLD_LIBRARY_PATH="$CONV" LD_LIBRARY_PATH="$CONV" ./x2t "$PARAMS" )
rc=$?
set -e
rm -f "$PARAMS"

if [ $rc -ne 0 ]; then
	echo "x2t failed with code $rc (format $FMT)" >&2
	exit $rc
fi
echo "wrote $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, format $FMT)"
