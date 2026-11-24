#!/usr/bin/env bash
# Rebuild compact vertical stacks (each frame scaled to 1280 px wide, aspect kept) for every clip dir under $1.
set -u
root="$1"
for d in "$root"/*/; do
  name=$(basename "$d")
  convert "$d/frame_start.jpg" -resize 1280x "$d/s1.jpg"
  convert "$d/frame_middle.jpg" -resize 1280x "$d/s2.jpg"
  convert "$d/frame_end.jpg" -resize 1280x "$d/s3.jpg"
  convert "$d/s1.jpg" "$d/s2.jpg" "$d/s3.jpg" -background white -splice 0x8 -append -gravity North -splice 0x40 -pointsize 26 -annotate +0+6 "$name  (start / middle / end)" "$d/stack2.jpg"
  echo "$name ok"
done
