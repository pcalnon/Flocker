#!/usr/bin/env bash
# For each Commons file title in $2.., fetch thumbnails at 10/35/60/85 percent of duration into dir $1, tile per file.
set -u
out="$1"
shift
mkdir -p "$out"
n=0
for t in "$@"; do
  n=$((n+1))
  dur=$(curl -fsSL --max-time 60 --retry 3 -A 'research-video-fetch/1.0' -G 'https://commons.wikimedia.org/w/api.php' --data-urlencode 'action=query' --data-urlencode "titles=$t" --data-urlencode 'prop=imageinfo' --data-urlencode 'iiprop=size' --data-urlencode 'format=json' | jq -r '.query.pages[].imageinfo[0].duration')
  args=()
  for f in 10 35 60 85; do
    s=$(python3 -I -c "import sys; print(int(float(sys.argv[1])*int(sys.argv[2])/100))" "$dur" "$f")
    u=$(curl -fsSL --max-time 60 --retry 3 -A 'research-video-fetch/1.0' -G 'https://commons.wikimedia.org/w/api.php' --data-urlencode 'action=query' --data-urlencode "titles=$t" --data-urlencode 'prop=imageinfo' --data-urlencode 'iiprop=url' --data-urlencode 'iiurlwidth=480' --data-urlencode "iiurlparam=seek=$s" --data-urlencode 'format=json' | jq -r '.query.pages[].imageinfo[0].thumburl')
    curl -fsSL --max-time 120 --retry 3 -A 'research-video-fetch/1.0' -o "$out/c${n}_${f}.jpg" "$u"
    args+=(-label "${s}s" "$out/c${n}_${f}.jpg")
  done
  montage "${args[@]}" -tile 4x1 -geometry 400x225+2+2 -title "file $n (dur ${dur}s)" "$out/commons_${n}.jpg"
  echo "$n $t dur=$dur"
done
