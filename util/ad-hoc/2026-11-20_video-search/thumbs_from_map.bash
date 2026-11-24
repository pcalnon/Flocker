#!/usr/bin/env bash
# Download thumbnails from a "<id> <url>" map file ($1) into dir $2 (as <id>.jpg), then tile ALL ids in map into sheets with prefix $3.
set -u
map="$1"; dir="$2"; prefix="$3"
mkdir -p "$dir"
while read -r id url; do
  [ -z "$id" ] && continue
  [ -s "$dir/$id.jpg" ] && continue
  sep='?'; case "$url" in *\?*) sep='&';; esac
  curl -fsSL --retry 3 -A 'research-video-fetch/1.0' -o "$dir/$id.jpg" "${url}${sep}auto=compress&w=400" || echo "FAIL $id"
done < "$map"
mapfile -t list < <(awk 'NF{print $1}' "$map")
n=${#list[@]}; per=20; sheet=0
for ((i=0; i<n; i+=per)); do
  args=()
  for id in "${list[@]:i:per}"; do
    [ -s "$dir/$id.jpg" ] && args+=(-label "$id" "$dir/$id.jpg")
  done
  sheet=$((sheet+1))
  montage "${args[@]}" -tile 4x -geometry 400x225+4+4 -pointsize 18 "${prefix}_$(printf '%02d' $sheet).jpg"
  echo "sheet ${prefix}_$(printf '%02d' $sheet).jpg: $(( ${#args[@]} / 3 )) images"
done
