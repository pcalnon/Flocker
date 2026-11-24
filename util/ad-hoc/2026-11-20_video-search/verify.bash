#!/usr/bin/env bash
# For each video in dir $1: print ffprobe summary + sha256; extract start/middle/end frames into $2/<base>/;
# build a vertical 3-frame stack (1280 px wide) $2/<base>/stack.jpg for viewing.
set -u
src="$1"
out="$2"
for f in "$src"/*.mp4 "$src"/*.webm; do
  if [ ! -f "$f" ]; then continue; fi
  base=$(basename "$f")
  stem="${base%.*}"
  mkdir -p "$out/$stem"
  info=$(/usr/bin/ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile,width,height,r_frame_rate,avg_frame_rate,nb_frames,pix_fmt -show_entries format=duration,size,bit_rate,format_name -of compact=p=0:nk=0 "$f" | tr '\n' ' ')
  dur=$(/usr/bin/ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
  mid=$(python3 -I -c "import sys; print(round(float(sys.argv[1])/2, 2))" "$dur")
  endt=$(python3 -I -c "import sys; print(round(max(float(sys.argv[1])-0.6, 0), 2))" "$dur")
  /usr/bin/ffmpeg -nostdin -v error -y -ss 0.3 -i "$f" -frames:v 1 -q:v 2 "$out/$stem/frame_start.jpg"
  /usr/bin/ffmpeg -nostdin -v error -y -ss "$mid" -i "$f" -frames:v 1 -q:v 2 "$out/$stem/frame_middle.jpg"
  /usr/bin/ffmpeg -nostdin -v error -y -ss "$endt" -i "$f" -frames:v 1 -q:v 2 "$out/$stem/frame_end.jpg"
  montage -label 'start 0.3s' "$out/$stem/frame_start.jpg" -label "middle ${mid}s" "$out/$stem/frame_middle.jpg" -label "end ${endt}s" "$out/$stem/frame_end.jpg" -tile 1x -geometry 1280x1280+0+4 -pointsize 22 -title "$base" "$out/$stem/stack.jpg"
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  echo "== $base"
  echo "   $info"
  echo "   sha256=$sha"
done
