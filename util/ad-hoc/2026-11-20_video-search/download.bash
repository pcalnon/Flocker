#!/usr/bin/env bash
# Download "<filename> <url>" pairs from $1 into directory $2; append "<filename> <retrieved-utc> <bytes> <http>" to $3.
set -u
list="$1"
dest="$2"
log="$3"
while read -r name url; do
  if [ -z "$name" ]; then continue; fi
  if [ -s "$dest/$name" ]; then echo "skip $name (exists)"; continue; fi
  when=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  res=$(curl -fL --retry 3 -sS -A 'research-video-fetch/1.0' -o "$dest/$name" -w '%{size_download} %{http_code}' "$url")
  echo "$name $when $res" | tee -a "$log"
done < "$list"
