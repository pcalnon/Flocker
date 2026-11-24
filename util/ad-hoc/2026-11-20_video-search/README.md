# Video-search scripts (2026-11-20)

Single-use scripts written by the agent that found the clips in `videos/raw/` on 2026-11-20.
They ran from a scratch folder in another repository and were moved here on 2026-11-24 by
`util/ad-hoc/2026-11-24_move_work_files_from_juniper.py`. Every path is passed as an argument,
so they run from anywhere.

Their working data (candidate lists, download logs, low-resolution previews, frame sheets,
downloaded page snapshots and browser logs) is in `tmp/2026-11-20_video-search/`, which git
ignores. The results are recorded in `videos/raw/SOURCES.md`.

| Script | What it does |
|---|---|
| `commons_search.bash` | Searches Wikimedia Commons' File namespace for each query given as an argument |
| `commons_cat.bash` | Lists the members (files and subcategories) of Commons categories |
| `commons_info.bash` | Prints size, dimensions, duration, licence, author and description for Commons files |
| `commons_seek_thumbs.bash` | Fetches thumbnails at 10/35/60/85 % of each Commons video's duration and tiles them |
| `pexels_thumbs.bash` | Downloads Pexels poster thumbnails for a list of ids and builds labelled contact sheets |
| `thumbs_from_map.bash` | Downloads thumbnails from an `<id> <url>` map and tiles them into sheets |
| `preview_strips.bash` | Downloads a small preview of each candidate and extracts five frames |
| `restack.bash` | Rebuilds compact vertical frame stacks for every clip folder |
| `download.bash` | Downloads `<filename> <url>` pairs and appends `<filename> <retrieved-utc> <bytes> <http>` to a log |
| `verify.bash` | Prints each video's ffprobe summary and sha256, and extracts start, middle and end frames |
