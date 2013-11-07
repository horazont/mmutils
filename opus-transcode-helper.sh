#!/bin/sh
INPUT=$1
OUTPUT=`echo "../LQ-Musik/$1" | sed s/.flac/.opus/ | sed "y/:?\\!<>*/      /"`
OUTPUTDIR=`echo "$OUTPUT" | grep -Po "[^/]*/.*/"`
if [ -f "$OUTPUT" ]; then
  echo "$INPUT already converted."
  exit 0
else
  echo "Converting $INPUT..."
  mkdir -p "$OUTPUTDIR"
  oggenc -Q -q 7 -o "$OUTPUT" "$INPUT"
  echo "  $OUTPUT"
fi
