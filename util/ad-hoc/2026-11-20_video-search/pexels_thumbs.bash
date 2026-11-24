#!/usr/bin/env bash
# Download Pexels poster thumbnails for ids listed in $1 into $2, then build labelled contact sheets into $3.
# Usage: pexels_thumbs.bash <idfile> <thumbdir> <sheet-prefix>
set -u
ids="$1"; dir="$2"; prefix="$3"
mkdir -p "$dir"
while read -r id; do
  [ -z "$id" ] && continue
  [ -s "$dir/$id.jpg" ] && continue
  curl -fsSL --retry 3 -A 'research-video-fetch/1.0' -o "$dir/$id.jpg" "https://images.pexels.com/videos/$id/pexels-photo-$id.jpeg?auto=compress&w=400" || echo "FAIL $id"
done < "$ids"
mapfile -t list < <(grep -v '^$' "$ids")
n=${#list[@]}; per=20; sheet=0
for ((i=0; i<n; i+=per)); do
  args=()
  for id in "${list[@]:i:per}"; do
    [ -s "$dir/$id.jpg" ] && args+=(-label "$id" "$dir/$id.jpg")
  done
  sheet=$((sheet+1))
  montage "${args[@]}" -tile 4x -geometry 400x225+4+4 -pointsize 18 "${prefix}_$(printf '%02d' $sheet).jpg"
  echo "sheet ${prefix}_$(printf '%02d' $sheet).jpg: ${#args[@]} args"
done
