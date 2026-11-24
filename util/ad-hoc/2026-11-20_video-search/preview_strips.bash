#!/usr/bin/env bash
# For each "<id> <url>" in $1: download small preview into $2/<id>.mp4, extract 5 frames
# scaled to 320px wide into $3/parts/, and tile them into one labelled strip $3/strip_<id>.jpg.
set -u
list="$1"
pdir="$2"
sdir="$3"
mkdir -p "$pdir" "$sdir/parts"
while read -r id url; do
  if [ -z "$id" ]; then continue; fi
  f="$pdir/$id.mp4"
  if [ ! -s "$f" ]; then curl -fsSL --retry 3 -A 'research-video-fetch/1.0' -o "$f" "$url"; fi
  dur=$(/usr/bin/ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
  args=()
  for pct in 2 25 50 75 97; do
    t=$(python3 -I -c "import sys; print(round(float(sys.argv[1])*int(sys.argv[2])/100, 2))" "$dur" "$pct")
    out="$sdir/parts/f_${id}_${pct}.jpg"
    /usr/bin/ffmpeg -nostdin -v error -y -ss "$t" -i "$f" -frames:v 1 -vf "scale=320:-2" "$out"
    args+=(-label "${pct}pct t=${t}s" "$out")
  done
  montage "${args[@]}" -tile 5x1 -geometry +2+2 -pointsize 13 -title "$id dur=${dur}" "$sdir/strip_$id.jpg"
  echo "$id dur=$dur ok"
done < "$list"
