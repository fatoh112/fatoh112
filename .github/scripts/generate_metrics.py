#!/usr/bin/env python3
"""Generate a public profile card from aggregate GitHub data only."""
import html, json, os, re, sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = "https://api.github.com/graphql"
LOGIN = "fatoh112"
CAIRO = ZoneInfo("Africa/Cairo")
TOKEN = os.environ.get("METRICS_TOKEN", "")
if not TOKEN:
    print("METRICS_TOKEN is unavailable.", file=sys.stderr)
    raise SystemExit(1)


def graphql(query, variables):
    request = Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
        "Accept": "application/vnd.github+json", "User-Agent": "fatoh112-profile-dashboard"})
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise RuntimeError("GitHub GraphQL request failed") from None
    if payload.get("errors") or not payload.get("data"):
        raise RuntimeError("GitHub GraphQL returned an unusable response")
    return payload["data"]


def esc(value):
    return html.escape(str(value), quote=True)


def fmt(value):
    return f"{int(value):,}"


def date_range(value):
    if not value:
        return "No active streak"
    first, last = value
    if first.year == last.year:
        return f"{first.strftime('%b %d')} – {last.strftime('%b %d, %Y')}"
    return f"{first.strftime('%b %d, %Y')} – {last.strftime('%b %d, %Y')}"


now = datetime.now(CAIRO)
today = now.date()
start_day = today - timedelta(days=364)
main_query = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    followers { totalCount }
    publicRepositories: repositories(ownerAffiliations: [OWNER], privacy: PUBLIC) { totalCount }
    privateRepositories: repositories(ownerAffiliations: [OWNER], privacy: PRIVATE) { totalCount }
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
      totalCommitContributions totalPullRequestContributions
      totalPullRequestReviewContributions totalIssueContributions
    }
  }
}
"""
start_dt = datetime.combine(start_day, time.min, CAIRO)
user = graphql(main_query, {"login": LOGIN, "from": start_dt.isoformat(), "to": now.isoformat()}).get("user")
if not user:
    raise RuntimeError("GitHub user data is unavailable")
collection = user["contributionsCollection"]
calendar = collection["contributionCalendar"]

# This query intentionally requests no repository identities or repository-level text.
language_query = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: [OWNER]) {
      nodes { languages(first: 100, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
language_sizes, language_colors, cursor = Counter(), {}, None
while True:
    repos = graphql(language_query, {"login": LOGIN, "after": cursor})["user"]["repositories"]
    for repo in repos["nodes"]:
        for edge in repo["languages"]["edges"]:
            language = edge["node"]
            name = language["name"]
            language_sizes[name] += edge["size"]
            if language.get("color"):
                language_colors[name] = language["color"]
    page = repos["pageInfo"]
    if not page["hasNextPage"]:
        break
    cursor = page["endCursor"]

public_count = user["publicRepositories"]["totalCount"]
private_count = user["privateRepositories"]["totalCount"]
metrics = {
    "contributions": calendar["totalContributions"],
    "current": 0, "current_range": None, "longest": 0, "longest_range": None,
    "repos": public_count + private_count, "private": private_count, "public": public_count,
    "followers": user["followers"]["totalCount"], "commits": collection["totalCommitContributions"],
    "prs": collection["totalPullRequestContributions"], "reviews": collection["totalPullRequestReviewContributions"],
    "issues": collection["totalIssueContributions"], "updated": now.strftime("%b %d, %Y").upper(),
}
daily = {}
for week in calendar["weeks"]:
    for item in week["contributionDays"]:
        day = date.fromisoformat(item["date"])
        if start_day <= day <= today:
            daily[day] = item["contributionCount"]
for offset in range(365):
    daily.setdefault(start_day + timedelta(days=offset), 0)

anchor = today if daily.get(today, 0) else today - timedelta(days=1)
if daily.get(anchor, 0):
    first = anchor
    while first > start_day and daily.get(first - timedelta(days=1), 0):
        first -= timedelta(days=1)
    metrics["current"] = (anchor - first).days + 1
    metrics["current_range"] = (first, anchor)

best, best_range = 0, None
run_start = previous = None
run = 0
for day in sorted(daily):
    if daily[day]:
        if previous is not None and day == previous + timedelta(days=1):
            run += 1
        else:
            run_start, run = day, 1
        if run > best:
            best, best_range = run, (run_start, day)
        previous = day
    else:
        previous, run = None, 0
metrics["longest"], metrics["longest_range"] = best, best_range

parts = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="586" viewBox="0 0 960 586" role="img" aria-labelledby="title desc">',
    '<title id="title">Fatoh GitHub development activity</title>',
    '<desc id="desc">Privacy-safe summary of contributions, repository totals, activity, and aggregated programming languages over the last 12 months.</desc>',
    '<rect width="960" height="586" rx="22" fill="#181a25"/>',
    '<text x="30" y="34" fill="#f4f3f8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="18" font-weight="700">GitHub development activity</text>',
    '<text x="30" y="54" fill="#9295a8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">A private-safe view of the last 12 months</text>',
    f'<text x="930" y="38" text-anchor="end" fill="#aeb0c0" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">UPDATED {metrics["updated"]}</text>',
]


def card(x, y, width, height, label, value, accent, note=None, size=25):
    parts.extend([
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="15" fill="#202230" stroke="#303345"/>',
        f'<rect x="{x}" y="{y+15}" width="3" height="{height-30}" rx="1.5" fill="{accent}"/>',
        f'<text x="{x+18}" y="{y+27}" fill="#a1a4b5" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11" font-weight="600" letter-spacing=".4">{esc(label.upper())}</text>',
        f'<text x="{x+18}" y="{y+63}" fill="#f7f6fb" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="750">{esc(fmt(value) if isinstance(value, int) else value)}</text>',
    ])
    if note:
        parts.append(f'<text x="{x+18}" y="{y+86}" fill="#818597" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{esc(note)}</text>')


gap = 14
top_w = (900 - gap * 2) // 3
card(30, 72, top_w, 112, "Total contributions", metrics["contributions"], "#a855f7", "Last 12 months", 29)
card(30 + top_w + gap, 72, top_w, 112, "Current streak", metrics["current"], "#60a5fa", date_range(metrics["current_range"]), 29)
card(30 + 2 * (top_w + gap), 72, top_w, 112, "Longest streak", metrics["longest"], "#c084fc", date_range(metrics["longest_range"]), 29)

parts.append('<text x="30" y="211" fill="#b8bac8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11" font-weight="700" letter-spacing=".8">REPOSITORIES &amp; COMMUNITY</text>')
small_gap = 12
small_w = (900 - 3 * small_gap) // 4
for i, (label, key, color) in enumerate([
    ("Total repos", "repos", "#a855f7"), ("Private repos", "private", "#c084fc"),
    ("Public repos", "public", "#60a5fa"), ("Followers", "followers", "#7dd3fc"),
]):
    card(30 + i * (small_w + small_gap), 222, small_w, 76, label, metrics[key], color, size=24)

parts.append('<text x="30" y="326" fill="#b8bac8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11" font-weight="700" letter-spacing=".8">ACTIVITY · LAST 12 MONTHS</text>')
for i, (label, key, color) in enumerate([
    ("Commits", "commits", "#a855f7"), ("Pull requests", "prs", "#60a5fa"),
    ("PR reviews", "reviews", "#c084fc"), ("Issues", "issues", "#7dd3fc"),
]):
    card(30 + i * (small_w + small_gap), 337, small_w, 76, label, metrics[key], color, size=24)

lang_y = 435
parts.extend([
    f'<rect x="30" y="{lang_y}" width="900" height="119" rx="15" fill="#202230" stroke="#303345"/>',
    f'<text x="48" y="{lang_y+25}" fill="#f2f1f7" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12" font-weight="700">TOP LANGUAGES</text>',
    f'<text x="912" y="{lang_y+25}" text-anchor="end" fill="#888b9e" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">Aggregated across accessible owned repositories</text>',
])
palette = ["#a855f7", "#60a5fa", "#34d399", "#f59e0b", "#f472b6", "#22d3ee"]
total_bytes = sum(language_sizes.values())
entries = []
for name, size in language_sizes.most_common(6):
    if not name or size <= 0 or not re.fullmatch(r"[A-Za-z0-9+#. _-]{1,28}", name):
        continue
    pct = size * 100 / total_bytes if total_bytes else 0
    if pct < 1 and len(entries) >= 3:
        continue
    color = language_colors.get(name, palette[len(entries) % len(palette)])
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = palette[len(entries) % len(palette)]
    entries.append((name, pct, color))
if total_bytes and entries:
    used = 0
    for i, (_, pct, color) in enumerate(entries):
        width = round(864 * pct / 100) if i < len(entries) - 1 else 864 - used
        width = max(0, min(width, 864 - used))
        if width:
            parts.append(f'<rect x="{48+used}" y="{lang_y+39}" width="{width}" height="9" rx="4.5" fill="{esc(color)}"/>')
            used += width
    if used < 864:
        parts.append(f'<rect x="{48+used}" y="{lang_y+39}" width="{864-used}" height="9" rx="4.5" fill="#343646"/>')
    for i, (name, pct, color) in enumerate(entries):
        col, row = i % 3, i // 3
        x, y = 48 + col * 288, lang_y + 75 + row * 23
        parts.extend([
            f'<circle cx="{x+5}" cy="{y-4}" r="4" fill="{esc(color)}"/>',
            f'<text x="{x+16}" y="{y}" fill="#e7e6ee" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">{esc(name)}</text>',
            f'<text x="{x+270}" y="{y}" text-anchor="end" fill="#a8aabb" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">{pct:.1f}%</text>',
        ])
else:
    parts.append(f'<text x="48" y="{lang_y+71}" fill="#9699aa" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">No language data available</text>')

parts.extend([
    '<text x="30" y="574" fill="#85889a" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">Private activity contributes to totals; private repository identities are never included.</text>',
    '</svg>',
])
with open("github-metrics.svg", "w", encoding="utf-8", newline="\n") as output:
    output.write("\n".join(parts) + "\n")
print("Generated privacy-safe GitHub dashboard.")
