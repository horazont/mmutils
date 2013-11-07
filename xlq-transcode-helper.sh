#!/bin/sh
INPUT=$1
OUTPUT=`echo "../XLQ-Musik/$1" | sed s/.flac/.mp3/ | sed "y/*:?\\!<>/      /"`
OUTPUTDIR=`echo "$OUTPUT" | grep -Po "[^/]*/.*/"`
if [ -f "$OUTPUT" ]; then
  echo "$INPUT already converted."
  exit 0
else
  echo "Converting $INPUT..."
  mkdir -p "$OUTPUTDIR"
  # oggenc -Q -b 280 -o "$OUTPUT" "$INPUT"
  METADATA=`metaflac --list "$INPUT"`
  TITLE=`echo "$METADATA" | grep -Po "(?<=TITLE=).*$"`
  ARTIST=`echo "$METADATA" | grep -Po "(?<=ARTIST=).*$"`
  ALBUM=`echo "$METADATA" | grep -Po "(?<=ALBUM=).*$"`
  TRACKNUMBER=`echo "$METADATA" | grep -Po "(?<=TRACKNUMBER=)[0-9]+"`
  DISCNUMBER=`echo "$METADATA" | grep -Po "(?<=DISCNUMBER=)[0-9]+"`
  if [ ! $? == 0 ]; then
    DISCNUMBER="0"
  fi
  FINAL_TRACKNUMBER=`echo "$DISCNUMBER"\`echo "$TRACKNUMBER" | sed -r "s/^([0-9])$/0\1/"\``
  flac -dc "$INPUT" | lame -b 256 -h --add-id3v2 --tt "$TITLE" --ta "$ARTIST" --tl "$ALBUM" --tn "$FINAL_TRACKNUMBER" - "$OUTPUT"
  echo "  $OUTPUT"
fi
