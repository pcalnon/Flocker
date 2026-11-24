#!/usr/bin/env python3
"""Validate where Flocker's tools come from, before adding or upgrading one.

Project: Flocker
File: util/validate_tool_sources.py
Purpose: read-only source checks for the conda environment's tools and the project's MCP servers
Author: Paul Calnon
Created: 2026-11-20, as util/ad-hoc/2026-11-20_validate_tool_sources.py; promoted here on 2026-11-24
License: CC0 1.0 (see LICENSE)

Read-only: it makes HTTPS GET requests, plus the POSTs of an MCP initialize and tools/list handshake.

Checks:
  1. Each conda-forge feedstock exists, is not archived, and its recipe builds from the official
     upstream source URL.
  2. Each upstream GitHub repository: owner, owner type, stars, licence, last push, archived flag.
  3. A package's recent PyPI release history (useful for long-dormant or newly revived projects).
  4. The dependencies a GitHub commit declares (for tools installed from GitHub, not an index).
  5. The remote MCP endpoints answer initialize + tools/list. Tokens are read from the
     environment and never printed.

Usage:
  python3 util/validate_tool_sources.py                 # the whole recorded toolchain, MCP included
  python3 util/validate_tool_sources.py --feedstock pytest --upstream pytest-dev/pytest
  python3 util/validate_tool_sources.py --pypi motmetrics --github-deps cheind/py-motmetrics@e5ae766fab03b804f485d7c95ee1809b94d32dcc

With any selection option, only the named checks run. GitHub allows 60 unauthenticated API requests
an hour; a full run makes about 45. Set GITHUB_TOKEN to raise the limit (it is sent only to
api.github.com).
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.request

UA = "tool-validation/1.0"

# The recorded toolchain: notes/FLOCKER_2026-11-20_VIDEO-TOOLCHAIN-SETUP.md, extended by
# notes/FLOCKER_2026-11-24_TEAMTRACK-EVALUATION-HARNESS.md (evaluation and development tools).
FEEDSTOCKS = ["pytorch-cpu", "torchvision", "opencv", "ffmpeg", "ultralytics", "supervision", "mplsoccer", "yt-dlp", "kaggle", "huggingface_hub", "gdown", "lap", "filterpy", "pytest", "black", "isort", "flake8"]

UPSTREAM = ["pytorch/pytorch", "pytorch/vision", "opencv/opencv", "FFmpeg/FFmpeg", "ultralytics/ultralytics", "roboflow/supervision", "andrewRowlinson/mplsoccer", "yt-dlp/yt-dlp", "Kaggle/kaggle-api", "huggingface/huggingface_hub", "wkentaro/gdown", "gatagat/lap", "rlabbe/filterpy", "roboflow/sports", "AtomScott/SportsLabKit", "upstash/context7", "cheind/py-motmetrics", "pytest-dev/pytest", "psf/black", "PyCQA/isort", "PyCQA/flake8"]

PYPI = ["filterpy", "motmetrics"]

GITHUB_DEPS = ["roboflow/sports@42c80c06b6b65a7f89455b89fe31cdf4c38ba227", "cheind/py-motmetrics@e5ae766fab03b804f485d7c95ee1809b94d32dcc"]

MCP_ENDPOINTS = [("kaggle", "https://www.kaggle.com/mcp", "KAGGLE_API_TOKEN"), ("huggingface", "https://huggingface.co/mcp", "HF_TOKEN"), ("context7", "https://mcp.context7.com/mcp", None)]


def get(url, headers=None, data=None, method=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()


def check_feedstocks(feedstocks):
    print("== conda-forge feedstocks: repo | last push | archived | recipe source ==")
    for fs in feedstocks:
        repo = f"conda-forge/{fs}-feedstock"
        try:
            j = json.loads(get(f"https://api.github.com/repos/{repo}")[2])
        except Exception as e:
            print(f"{repo}: ERROR {e}")
            continue
        src = "?"
        for f in ("recipe/recipe.yaml", "recipe/meta.yaml"):
            try:
                t = get(f"https://raw.githubusercontent.com/{repo}/{j.get('default_branch', 'main')}/{f}")[2].decode()
            except urllib.error.HTTPError:
                continue
            m = re.search(r"^\s*(?:-\s*)?url:\s*(\S+)", t, re.M)
            if m:
                src = m.group(1)
                break
        print(f"{j['full_name']} | {j['pushed_at'][:10]} | archived={j['archived']} | {src}")


def check_upstream(repos):
    print("\n== upstream: repo | owner type | stars | license | last push | archived ==")
    for r in repos:
        try:
            j = json.loads(get(f"https://api.github.com/repos/{r}")[2])
            print(f"{j['full_name']} | {j['owner']['type']} | {j['stargazers_count']} | {(j.get('license') or {}).get('spdx_id')} | {j['pushed_at'][:10]} | archived={j['archived']}")
        except Exception as e:
            print(f"{r}: ERROR {e}")


def check_pypi(names):
    for name in names:
        print(f"\n== {name} on PyPI ==")
        try:
            j = json.loads(get(f"https://pypi.org/pypi/{name}/json", headers={"Accept": "application/json"})[2])
        except Exception as e:
            print(f"{name}: ERROR {e}")
            continue
        rel = sorted(((v, (fl[0]["upload_time"] if fl else "")) for v, fl in j["releases"].items()), key=lambda x: x[1])
        print("last releases:", rel[-3:])
        print("author:", j["info"].get("author"), "| home:", j["info"].get("home_page"), "| urls:", j["info"].get("project_urls"))


def check_github_deps(specs):
    for spec in specs:
        repo, _, ref = spec.partition("@")
        ref = ref or "main"
        print(f"\n== {repo} @ {ref}: dependency declarations ==")
        for f in ("pyproject.toml", "setup.py", "requirements.txt"):
            try:
                t = get(f"https://raw.githubusercontent.com/{repo}/{ref}/{f}")[2].decode()
            except urllib.error.HTTPError as e:
                print(f"{f}: HTTP {e.code}")
                continue
            block = re.findall(r"(?:install_requires|dependencies|requires)\s*=\s*\[(.*?)\]", t, re.S)
            print(f"{f}:", " || ".join(re.sub(r"\s+", " ", b).strip() for b in block) if block else t[:300].replace("\n", " "))


def probe_mcp(name, url, token_env):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token_env and os.environ.get(token_env):
        h["Authorization"] = "Bearer " + os.environ[token_env]

    def call(body):
        _, hd, b = get(url, headers=h, data=json.dumps(body).encode(), method="POST")
        return hd, b.decode()

    try:
        hd, _ = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}})
        if hd.get("mcp-session-id"):
            h["Mcp-Session-Id"] = hd["mcp-session-id"]
        call({"jsonrpc": "2.0", "method": "notifications/initialized"})
        _, t = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        payload = [line[5:].strip() for line in t.splitlines() if line.startswith("data:")]
        tools = [x["name"] for x in json.loads(payload[-1] if payload else t)["result"]["tools"]]
        print(f"{name} ({'auth' if 'Authorization' in h else 'no auth'}): {len(tools)} tools: {', '.join(tools)}")
    except Exception as e:
        print(f"{name}: ERROR {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Read-only source checks for Flocker's tools. With no selection option, checks the whole recorded toolchain.")
    ap.add_argument("--feedstock", action="append", default=[], metavar="NAME", help="conda-forge feedstock to check, without '-feedstock' (repeatable)")
    ap.add_argument("--upstream", action="append", default=[], metavar="OWNER/REPO", help="upstream GitHub repository to check (repeatable)")
    ap.add_argument("--pypi", action="append", default=[], metavar="NAME", help="PyPI project whose release history to print (repeatable)")
    ap.add_argument("--github-deps", action="append", default=[], metavar="OWNER/REPO@REF", help="print the dependencies a GitHub commit declares (repeatable)")
    ap.add_argument("--mcp", action="store_true", help="probe the MCP endpoints (always on in a full run)")
    args = ap.parse_args()
    selected = bool(args.feedstock or args.upstream or args.pypi or args.github_deps or args.mcp)
    if not selected:
        args.feedstock, args.upstream, args.pypi, args.github_deps, args.mcp = FEEDSTOCKS, UPSTREAM, PYPI, GITHUB_DEPS, True
    if args.feedstock:
        check_feedstocks(args.feedstock)
    if args.upstream:
        check_upstream(args.upstream)
    if args.pypi:
        check_pypi(args.pypi)
    if args.github_deps:
        check_github_deps(args.github_deps)
    if args.mcp:
        print("\n== MCP endpoints (initialize + tools/list) ==")
        for name, url, token_env in MCP_ENDPOINTS:
            probe_mcp(name, url, token_env)


if __name__ == "__main__":
    main()
