from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kdi-mcp")
logging.getLogger("httpx").setLevel(logging.WARNING)

KDI_API_URL = "https://www.kdi.re.kr/KDIOpenAPI"
KDI_API_KEY = os.getenv("KDI_API_KEY", "").strip()
KDI_CATEGORY_CODES = [
    code.strip()
    for code in os.getenv("KDI_CATEGORY_CODES", "A").split(",")
    if code.strip()
]
KDI_VERIFY_SSL = os.getenv("KDI_VERIFY_SSL", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}


class SearchResult(BaseModel):
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    results: list[SearchResult]


class FetchOutput(BaseModel):
    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LatestOutput(BaseModel):
    results: list[FetchOutput]


def normalize_date(value: str | None) -> date | None:
    if not value:
        return None

    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    match = re.search(r"(20\d{2})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def get_first(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def make_id(item: dict[str, Any], category_code: str) -> str:
    detail = get_first(item, "DETAIL_PAGE", "detail_page")
    title = get_first(item, "PUB_NM_KORN", "PUB_NM_ENG", "TITLE")
    issued = get_first(item, "ISSU_DT", "REG_DT", "DATE")
    raw = detail or f"{category_code}:{issued}:{title}"
    return re.sub(r"[^a-zA-Z0-9_.:/?=&%-]+", "-", raw).strip("-")[:240]


def to_absolute_url(url: str) -> str:
    if not url:
        return "https://www.kdi.re.kr/"
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.kdi.re.kr{url}"
    return f"https://www.kdi.re.kr/{url}"


def build_text(item: dict[str, Any]) -> str:
    title = get_first(item, "PUB_NM_KORN", "PUB_NM_ENG", "TITLE")
    summary = get_first(item, "SUMM_KORN", "SUMM_ENG", "SUMMARY", "CONT")
    contents = get_first(item, "PUB_CN", "CONTENT")
    keyword = get_first(item, "PUB_KEYWORD", "KEYWORD")

    parts = [
        f"Title: {title}",
        f"Type: {get_first(item, 'PUB_CD_NM', 'PUB_CD')}",
        f"Issued: {get_first(item, 'ISSU_DT')}",
        f"Author: {get_first(item, 'MAIN_AUT_NM', 'SUB_AUT_NM', 'CO_AUT_NM')}",
    ]
    if keyword:
        parts.append(f"Keywords: {keyword}")
    if summary:
        parts.append(f"Summary:\n{summary}")
    if contents:
        parts.append(f"Contents:\n{contents}")

    return "\n\n".join(part for part in parts if part.strip())


def to_fetch_output(item: dict[str, Any], category_code: str) -> FetchOutput:
    item_id = make_id(item, category_code)
    title = get_first(item, "PUB_NM_KORN", "PUB_NM_ENG", "TITLE") or "KDI research material"
    url = to_absolute_url(get_first(item, "DETAIL_PAGE", "URL"))
    issued = get_first(item, "ISSU_DT")

    metadata = {
        "source": "KDI Open API",
        "category_code": category_code,
        "category_name": get_first(item, "PUB_CD_NM", "PUB_CD"),
        "issued_date": issued,
        "authors": get_first(item, "MAIN_AUT_NM", "SUB_AUT_NM", "CO_AUT_NM"),
        "language": get_first(item, "PUB_LANG"),
        "topic": get_first(item, "TOPIC_ARR"),
    }

    return FetchOutput(
        id=item_id,
        title=title,
        text=build_text(item),
        url=url,
        metadata={key: value for key, value in metadata.items() if value},
    )


async def call_kdi_api(
    category_code: str,
    *,
    search_key: str = "ALL",
    search_value: str = "",
) -> list[dict[str, Any]]:
    if not KDI_API_KEY:
        raise RuntimeError("KDI_API_KEY is not configured")

    params = {
        "type": "json",
        "apiKey": KDI_API_KEY,
        "cd": category_code,
        "srhKey": search_key,
    }
    if search_value:
        params["srhValue"] = search_value

    url = f"{KDI_API_URL}?{urlencode(params)}"
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        verify=KDI_VERIFY_SSL,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        return []

    archives = (
        payload.get("ARCHIVES")
        or payload.get("ARCHIVE")
        or payload.get("archives")
        or payload.get("archive")
        or payload.get("data")
        or []
    )
    if isinstance(archives, dict):
        archives = archives.get("ARCHIVE") or archives.get("archive") or archives.get("items") or []
    if isinstance(archives, list):
        return [item for item in archives if isinstance(item, dict)]
    return []


async def collect_items(query: str = "") -> list[FetchOutput]:
    items: list[FetchOutput] = []
    for category_code in KDI_CATEGORY_CODES:
        try:
            raw_items = await call_kdi_api(
                category_code,
                search_key="ALL",
                search_value=query.strip(),
            )
        except Exception as exc:
            logger.warning("Skipping KDI category %s: %s", category_code, exc)
            continue
        items.extend(to_fetch_output(item, category_code) for item in raw_items)

    seen: set[str] = set()
    deduped: list[FetchOutput] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        deduped.append(item)
    return deduped


def sort_newest(items: list[FetchOutput]) -> list[FetchOutput]:
    def key(item: FetchOutput) -> date:
        return normalize_date(str(item.metadata.get("issued_date", ""))) or date.min

    return sorted(items, key=key, reverse=True)


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="KDI Research",
        instructions=(
            "Search and fetch Korean Development Institute research materials "
            "from the KDI Open API. Prefer latest_kdi_research for daily updates."
        ),
    )

    @mcp.tool(output_schema=SearchOutput.model_json_schema())
    async def search(query: str) -> SearchOutput:
        """Search KDI research materials by title, author, keyword, or content."""
        items = sort_newest(await collect_items(query))
        results = [
            SearchResult(id=item.id, title=item.title, url=item.url)
            for item in items[:20]
        ]
        return SearchOutput(results=results)

    @mcp.tool(output_schema=FetchOutput.model_json_schema())
    async def fetch(id: str) -> FetchOutput:
        """Fetch one KDI research material by the id returned from search."""
        items = await collect_items("")
        for item in items:
            if item.id == id:
                return item
        raise ValueError(f"KDI item not found: {id}")

    @mcp.tool(output_schema=LatestOutput.model_json_schema())
    async def latest_kdi_research(since: str = "") -> LatestOutput:
        """Return KDI research materials issued since YYYY-MM-DD."""
        since_date = normalize_date(since) if since else date.today() - timedelta(days=1)
        if since_date is None:
            raise ValueError("since must be a date such as 2026-05-27")

        items = sort_newest(await collect_items(""))
        recent = [
            item
            for item in items
            if (normalize_date(str(item.metadata.get("issued_date", ""))) or date.min)
            >= since_date
        ]
        return LatestOutput(results=recent[:30])

    return mcp


def main() -> None:
    if not KDI_API_KEY:
        raise RuntimeError("Set KDI_API_KEY before starting the server")

    port = int(os.getenv("PORT", "8000"))
    server = create_server()

    logger.info("Starting KDI MCP server on 0.0.0.0:%s", port)
    server.run(transport="sse", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
