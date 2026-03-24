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


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or not str(value).strip()):
        raise ValueError(f"Missing required environment variable: {name}")
    return "" if value is None else str(value).strip()


def get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


USERNAME_GITHUB = get_env("USERNAME_GITHUB", "Rapter1990")
PROFILE_REPO = get_env("PROFILE_REPO", USERNAME_GITHUB)
MEDIUM_USERNAME = get_env("MEDIUM_USERNAME", "")
README_PATH = Path(get_env("README_PATH", "README.md"))

PROJECT_LIMIT = get_int_env("PROJECT_LIMIT", 5)
POST_LIMIT = get_int_env("POST_LIMIT", 5)

EXCLUDED_REPOS = {
    item.strip()
    for item in get_env("EXCLUDED_REPOS", PROFILE_REPO).split(",")
    if item.strip()
}


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_json(url: str, headers: dict[str, str] | None = None):
    return json.loads(fetch_text(url, headers=headers))


def format_github_date(iso_value: str) -> str:
    return datetime.fromisoformat(iso_value.replace("Z", "+00:00")).strftime("%B %Y")


def format_medium_date(pub_date: str) -> str:
    return parsedate_to_datetime(pub_date).strftime("%B %Y")


def get_github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{PROFILE_REPO}-readme-updater",
    }

    token = os.getenv("TOKEN_GITHUB")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def fetch_latest_projects() -> list[dict[str, str]]:
    url = (
        f"https://api.github.com/users/{USERNAME_GITHUB}/repos"
        f"?type=owner&sort=created&direction=desc&per_page=100"
    )

    repos = fetch_json(url, headers=get_github_headers())

    latest_projects: list[dict[str, str]] = []

    for repo in repos:
        repo_name = repo.get("name", "")

        if not repo_name:
            continue
        if repo_name in EXCLUDED_REPOS:
            continue
        if repo.get("fork"):
            continue
        if repo.get("archived"):
            continue

        latest_projects.append(
            {
                "title": repo_name,
                "link": repo.get("html_url", ""),
                "date": format_github_date(repo.get("created_at", "")),
            }
        )

        if len(latest_projects) >= PROJECT_LIMIT:
            break

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
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()
        pub_date = item.findtext("pubDate", default="").strip()

        if not title or not link or not pub_date:
            continue

        posts.append(
            {
                "title": html.unescape(title),
                "link": link,
                "date": format_medium_date(pub_date),
            }
        )

    return posts


def build_project_cells(index: int, project: dict[str, str] | None) -> str:
    if not project:
        return """
      <td style="border:1px solid #ddd; padding:6px; text-align:center;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
""".rstrip("\n")

    title = html.escape(project["title"])
    link = html.escape(project["link"], quote=True)
    date = html.escape(project["date"])

    return f"""
      <td style="border:1px solid #ddd; padding:6px; text-align:center;">{index}</td>
      <td style="border:1px solid #ddd; padding:6px; white-space:nowrap;">{title}</td>
      <td style="border:1px solid #ddd; padding:6px;">
        <a href="{link}" target="_blank" rel="noopener noreferrer">View</a>
      </td>
      <td style="border:1px solid #ddd; padding:6px;">{date}</td>
""".rstrip("\n")


def build_post_cells(index: int, post: dict[str, str] | None) -> str:
    if not post:
        return """
      <td style="border:1px solid #ddd; padding:6px; text-align:center;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
      <td style="border:1px solid #ddd; padding:6px;"></td>
""".rstrip("\n")

    title = html.escape(post["title"])
    link = html.escape(post["link"], quote=True)
    date = html.escape(post["date"])

    return f"""
      <td style="border:1px solid #ddd; padding:6px; text-align:center;">{index}</td>
      <td style="border:1px solid #ddd; padding:6px; white-space:nowrap;">{title}</td>
      <td style="border:1px solid #ddd; padding:6px;">
        <a href="{link}" target="_blank" rel="noopener noreferrer">Read</a>
      </td>
      <td style="border:1px solid #ddd; padding:6px;">{date}</td>
""".rstrip("\n")


def build_html_table(projects: list[dict[str, str]], posts: list[dict[str, str]]) -> str:
    row_count = max(PROJECT_LIMIT, POST_LIMIT, len(projects), len(posts), 1)
    rows = []

    for i in range(row_count):
        project = projects[i] if i < len(projects) else None
        post = posts[i] if i < len(posts) else None

        rows.append(
            f"""    <tr>
{build_project_cells(i + 1, project)}
{build_post_cells(i + 1, post)}
    </tr>"""
        )

    return f"""<table style="width:100%; border-collapse:collapse;">
  <thead>
    <tr>
      <th colspan="4" style="border:1px solid #ddd; padding:8px; text-align:left;">Latest Projects</th>
      <th colspan="4" style="border:1px solid #ddd; padding:8px; text-align:left;">Latest Blog Posts</th>
    </tr>
    <tr>
      <th style="border:1px solid #ddd; padding:6px; width:5rem;">#</th>
      <th style="border:1px solid #ddd; padding:6px; width:16rem;">Title</th>
      <th style="border:1px solid #ddd; padding:6px; width:8rem;">Link</th>
      <th style="border:1px solid #ddd; padding:6px; width:8rem;">Date</th>

      <th style="border:1px solid #ddd; padding:6px; width:5rem;">#</th>
      <th style="border:1px solid #ddd; padding:6px; width:16rem;">Title</th>
      <th style="border:1px solid #ddd; padding:6px; width:8rem;">Link</th>
      <th style="border:1px solid #ddd; padding:6px; width:8rem;">Date</th>
    </tr>
  </thead>
  <tbody>
{chr(10).join(rows)}
  </tbody>
</table>"""


def replace_generated_block(readme_text: str, generated_html: str) -> str:
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
        flags=re.DOTALL,
    )

    replacement = f"{START_MARKER}\n{generated_html}\n{END_MARKER}"

    if not pattern.search(readme_text):
        raise ValueError(
            "README markers not found. Please add START/END markers first."
        )

    return pattern.sub(replacement, readme_text, count=1)


def main() -> None:
    if not README_PATH.exists():
        raise FileNotFoundError(f"{README_PATH} not found.")

    print("Configuration:")
    print(f"  USERNAME_GITHUB = {USERNAME_GITHUB}")
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