#!/usr/bin/env bash
# Search Wikimedia Commons File: namespace for each query given as an argument.
# Usage: commons_search.bash 'query one' 'query two' ...
set -u
UA='research-video-fetch/1.0'
for q in "$@"; do
  echo "=== $q"
  curl -fsSL --retry 3 -A "$UA" -G 'https://commons.wikimedia.org/w/api.php' \
    --data-urlencode 'action=query' --data-urlencode 'list=search' \
    --data-urlencode "srsearch=$q" --data-urlencode 'srnamespace=6' \
    --data-urlencode 'srlimit=60' --data-urlencode 'format=json' \
    | jq -r '.query.searchinfo.totalhits as $t | "hits=\($t)", (.query.search[] | .title)' \
    | grep -viE 'Kin Wikipedia|WP25'
done
