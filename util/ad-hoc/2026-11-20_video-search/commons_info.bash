#!/usr/bin/env bash
# Print imageinfo (size, dims, duration, license, author, description) for Commons File: titles.
# Usage: commons_info.bash 'File:One.webm' 'File:Two.webm' ...
set -u
UA='research-video-fetch/1.0'
for t in "$@"; do
  curl -fsSL --retry 3 -A "$UA" -G 'https://commons.wikimedia.org/w/api.php' \
    --data-urlencode 'action=query' --data-urlencode "titles=$t" \
    --data-urlencode 'prop=imageinfo' --data-urlencode 'iiprop=url|size|mime|extmetadata|timestamp|user' \
    --data-urlencode 'format=json' \
    | jq -r '.query.pages[] | "### \(.title)", (.imageinfo[0] | "  dims=\(.width)x\(.height) dur=\(.duration // "?") size=\(.size) mime=\(.mime)", "  url=\(.url)", "  page=\(.descriptionurl)", "  license=\(.extmetadata.LicenseShortName.value // "?") | \(.extmetadata.LicenseUrl.value // "?") | usage=\(.extmetadata.UsageTerms.value // "?")", "  artist=\(.extmetadata.Artist.value // "?" | gsub("<[^>]*>";""))", "  credit=\(.extmetadata.Credit.value // "?" | gsub("<[^>]*>";""))", "  desc=\(.extmetadata.ImageDescription.value // "?" | gsub("<[^>]*>";"") | .[0:400])", "  date=\(.extmetadata.DateTimeOriginal.value // "?" | gsub("<[^>]*>";""))", "  cats=\(.extmetadata.Categories.value // "?")")'
done
