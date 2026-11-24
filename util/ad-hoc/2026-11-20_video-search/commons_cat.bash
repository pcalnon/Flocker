#!/usr/bin/env bash
# List members (files and subcats) of Commons categories.
# Usage: commons_cat.bash 'Category:Foo' ...
set -u
UA='research-video-fetch/1.0'
for c in "$@"; do
  echo "=== $c"
  curl -fsSL --retry 3 -A "$UA" -G 'https://commons.wikimedia.org/w/api.php' \
    --data-urlencode 'action=query' --data-urlencode 'list=categorymembers' \
    --data-urlencode "cmtitle=$c" --data-urlencode 'cmlimit=500' \
    --data-urlencode 'cmtype=file|subcat' --data-urlencode 'format=json' \
    | jq -r '.query.categorymembers[] | .title'
done
