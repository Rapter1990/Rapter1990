from __future__ import annotations

import html
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

START_MARKER = "<!-- START_LATEST_PROJECTS_AND_POSTS -->"
END_MARKER = "<!-- END_LATEST_PROJECTS_AND_POSTS -->"

TABLE_STYLE = (
    'style="width:100%; border-collapse:collapse; margin-top:8px;"'
)
TH_GROUP_STYLE = (
    'style="border:1px solid #d0d7de; padding:10px; text-align:left; background-color:#f6f8fa;"'
)
TH_NUM_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; width:4rem; text-align:center; background-color:#f6f8fa;"'
)
TH_TITLE_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; width:26rem; text-align:left; background-color:#f6f8fa;"'
)
TH_LINK_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; width:7rem; text-align:center; background-color:#f6f8fa;"'
)
TH_DATE_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; width:10rem; text-align:left; background-color:#f6f8fa;"'
)

TD_NUM_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; text-align:center; vertical-align:top;"'
)
TD_TITLE_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; vertical-align:top; white-space:normal; word-break:break-word; line-height:1.5;"'
)
TD_LINK_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; text-align:center; vertical-align:top;"'
)
TD_DATE_STYLE = (
    'style="border:1px solid #d0d7de; padding:8px; vertical-align:top;"'
)


def get_first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default.strip()


def get_int_env(*names: str, default: int) -> int:
    raw = get_first_env(*names, default=str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable for {names} must be an integer.") from exc


GITHUB_USERNAME = get_first_env("USERNAME_GITHUB", "GITHUB_USERNAME", default="Rapter1990")
PROFILE_REPO = get_first_env("PROFILE_REPO", default=GITHUB_USERNAME)
MEDIUM_USERNAME = get_first_env("MEDIUM_USERNAME", default="")
README_PATH = Path(get_first_env("README_PATH", default="README.md"))

PROJECT_LIMIT = get_int_env("PROJECT_LIMIT", default=5)
POST_LIMIT = get_int_env("POST_LIMIT", default=5)

EXCLUDED_REPOS = {
    item.strip()
    for item in get_first_env("EXCLUDED_REPOS", default=PROFILE_REPO).split(",")
    if item.strip()
}


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_json(url: str, headers: dict[str, str] | None = None):
    return json.loads(fetch_text(url, headers=headers))


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def prettify_repo_name(repo_name: str) -> str:
    words = repo_name.replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words)


def format_github_full_date(iso_value: str) -> str:
    if not iso_value:
        return ""

    dt = parse_iso_datetime(iso_value)
    return f"{dt.day} {dt.strftime('%B %Y')}"


def format_medium_full_date(pub_date: str) -> str:
    dt = parsedate_to_datetime(pub_date)
    return f"{dt.day} {dt.strftime('%B %Y')}"


def get_github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{PROFILE_REPO}-readme-updater",
    }

    token = get_first_env("GITHUB_TOKEN", "TOKEN_GITHUB", default="")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers

def get_repo_activity_raw(repo: dict) -> str:
    return clean_text(
        repo.get("pushed_at")
        or repo.get("updated_at")
        or repo.get("created_at")
        or ""
    )

def get_repo_activity_datetime(repo: dict) -> datetime:
    raw_value = get_repo_activity_raw(repo)
    if not raw_value:
        return datetime.min
    return parse_iso_datetime(raw_value)


def fetch_latest_projects() -> list[dict[str, str]]:
    url = (
        f"https://api.github.com/users/{GITHUB_USERNAME}/repos"
        f"?type=owner&per_page=100"
    )

    repos = fetch_json(url, headers=get_github_headers())

    filtered_repos: list[dict] = []
    for repo in repos:
        repo_name = clean_text(repo.get("name"))
        if not repo_name:
            continue
        if repo_name in EXCLUDED_REPOS:
            continue
        if repo.get("fork"):
            continue
        if repo.get("archived"):
            continue

        filtered_repos.append(repo)

    # IMPORTANT:
    # Sort ALL repos by the full timestamp first.
    # This fixes cases where more than one repo belongs to the same month
    # like December 2025.
    filtered_repos.sort(
        key=lambda repo: (
            get_repo_activity_datetime(repo),
            clean_text(repo.get("name")).lower(),
        ),
        reverse=True,
    )

    latest_projects: list[dict[str, str]] = []

    for repo in filtered_repos[:PROJECT_LIMIT]:
        repo_name = clean_text(repo.get("name"))
        description = clean_text(repo.get("description"))
        title = description if description else prettify_repo_name(repo_name)

        activity_raw = get_repo_activity_raw(repo)

        latest_projects.append(
            {
                "title": title,
                "link": clean_text(repo.get("html_url")),
                "date": format_github_full_date(activity_raw) if activity_raw else ""
            }
        )

    return latest_projects

def fetch_latest_medium_posts() -> list[dict[str, str]]:
    if not MEDIUM_USERNAME:
        return []

    rss_url = f"https://medium.com/feed/@{MEDIUM_USERNAME}"
    xml_text = fetch_text(
        rss_url,
        headers={"User-Agent": f"{PROFILE_REPO}-readme-updater"},
    )

    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    posts: list[dict[str, str]] = []

    for item in channel.findall("item")[:POST_LIMIT]:
        title = clean_text(item.findtext("title", default=""))
        link = clean_text(item.findtext("link", default=""))
        pub_date = clean_text(item.findtext("pubDate", default=""))

        if not title or not link or not pub_date:
            continue

        posts.append(
            {
                "title": html.unescape(title),
                "link": link,
                "date": format_medium_full_date(pub_date),
            }
        )

    return posts

def build_empty_cells() -> str:
    return (
        f"<td {TD_NUM_STYLE}></td>"
        f"<td {TD_TITLE_STYLE}></td>"
        f"<td {TD_LINK_STYLE}></td>"
        f"<td {TD_DATE_STYLE}></td>"
    )


def build_project_cells(index: int, project: dict[str, str] | None) -> str:
    if not project:
        return build_empty_cells()

    title = html.escape(project["title"])
    link = html.escape(project["link"], quote=True)
    date = html.escape(project["date"])

    return (
        f"<td {TD_NUM_STYLE}>{index}</td>"
        f"<td {TD_TITLE_STYLE}>{title}</td>"
        f'<td {TD_LINK_STYLE}><a href="{link}" target="_blank" rel="noopener noreferrer">View</a></td>'
        f"<td {TD_DATE_STYLE}>{date}</td>"
    )


def build_post_cells(index: int, post: dict[str, str] | None) -> str:
    if not post:
        return build_empty_cells()

    title = html.escape(post["title"])
    link = html.escape(post["link"], quote=True)
    date = html.escape(post["date"])

    return (
        f"<td {TD_NUM_STYLE}>{index}</td>"
        f"<td {TD_TITLE_STYLE}>{title}</td>"
        f'<td {TD_LINK_STYLE}><a href="{link}" target="_blank" rel="noopener noreferrer">Read</a></td>'
        f"<td {TD_DATE_STYLE}>{date}</td>"
    )


def build_html_table(projects: list[dict[str, str]], posts: list[dict[str, str]]) -> str:
    row_count = max(PROJECT_LIMIT, POST_LIMIT, len(projects), len(posts), 1)

    rows: list[str] = []
    for i in range(row_count):
        project = projects[i] if i < len(projects) else None
        post = posts[i] if i < len(posts) else None

        rows.append(
            "<tr>"
            f"{build_project_cells(i + 1, project)}"
            f"{build_post_cells(i + 1, post)}"
            "</tr>"
        )

    return (
        f"<table {TABLE_STYLE}>"
        "<thead>"
        "<tr>"
        f"<th colspan=\"4\" {TH_GROUP_STYLE}>Latest Projects</th>"
        f"<th colspan=\"4\" {TH_GROUP_STYLE}>Latest Blog Posts</th>"
        "</tr>"
        "<tr>"
        f"<th {TH_NUM_STYLE}>#</th>"
        f"<th {TH_TITLE_STYLE}>Title</th>"
        f"<th {TH_LINK_STYLE}>Link</th>"
        f"<th {TH_DATE_STYLE}>Date</th>"
        f"<th {TH_NUM_STYLE}>#</th>"
        f"<th {TH_TITLE_STYLE}>Title</th>"
        f"<th {TH_LINK_STYLE}>Link</th>"
        f"<th {TH_DATE_STYLE}>Date</th>"
        "</tr>"
        "</thead>"
        "<tbody>"
        + "".join(rows) +
        "</tbody>"
        "</table>"
    )


def replace_generated_block(readme_text: str, generated_html: str) -> str:
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
        flags=re.DOTALL,
    )

    replacement = f"{START_MARKER}\n{generated_html}\n{END_MARKER}"

    if not pattern.search(readme_text):
        raise ValueError("README markers not found. Please add START/END markers first.")

    return pattern.sub(replacement, readme_text, count=1)


def main() -> None:
    if not README_PATH.exists():
        raise FileNotFoundError(f"{README_PATH} not found.")

    print("Configuration:")
    print(f"  GITHUB_USERNAME = {GITHUB_USERNAME}")
    print(f"  PROFILE_REPO    = {PROFILE_REPO}")
    print(f"  MEDIUM_USERNAME = {MEDIUM_USERNAME or '(empty)'}")
    print(f"  README_PATH     = {README_PATH}")
    print(f"  PROJECT_LIMIT   = {PROJECT_LIMIT}")
    print(f"  POST_LIMIT      = {POST_LIMIT}")
    print(f"  EXCLUDED_REPOS  = {sorted(EXCLUDED_REPOS)}")

    print("Fetching latest GitHub repositories...")
    projects = fetch_latest_projects()

    print("Fetching latest Medium posts...")
    try:
        posts = fetch_latest_medium_posts()
    except (HTTPError, URLError, ET.ParseError) as exc:
        print(f"Warning: could not fetch Medium posts: {exc}")
        posts = []

    print("Generating HTML block...")
    generated_html = build_html_table(projects, posts)

    original = README_PATH.read_text(encoding="utf-8")
    updated = replace_generated_block(original, generated_html)

    if updated == original:
        print("README already up to date. No changes needed.")
        return

    README_PATH.write_text(updated, encoding="utf-8")
    print("README updated successfully.")


if __name__ == "__main__":
    main()