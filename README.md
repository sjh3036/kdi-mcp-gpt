# KDI MCP Server for ChatGPT Tasks

This project wraps the KDI Open API as a remote MCP server so ChatGPT can check new KDI research materials through an app/connector and use it from Tasks.

## What It Exposes

- `search`: Finds KDI research materials by query.
- `fetch`: Returns full metadata and summary text for one item.
- `latest_kdi_research`: Returns items issued since a given date, useful for daily ChatGPT Tasks.

The `search` and `fetch` tools follow the compatibility shape recommended for ChatGPT data-only MCP apps.

## Local Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `KDI_API_KEY`.

Run:

```powershell
python server.py
```

The MCP endpoint is:

```text
http://localhost:8000/sse/
```

For ChatGPT, deploy this server to a public HTTPS host and use the deployed `/sse/` URL.

## Deploy Notes

Set these environment variables in your hosting provider:

- `KDI_API_KEY`: your KDI Open API key.
- `KDI_CATEGORY_CODES`: comma-separated category codes to scan.
- `KDI_VERIFY_SSL`: keep `true` in production. Set `false` only if local Python cannot verify KDI's certificate.
- `PORT`: usually provided by the host.

Good simple hosts: Render, Railway, Replit, or a small VPS. ChatGPT needs a remote HTTPS URL.

### Render Example

Create a new Web Service and use:

```text
Build command: pip install -r requirements.txt
Start command: python server.py
```

Then add `KDI_API_KEY` and `KDI_CATEGORY_CODES` in Environment.

## ChatGPT Task Prompt

Use this after the MCP app is connected:

```text
매일 오전 8시에 연결된 KDI MCP 앱을 사용해 KDI Open API의 신규 연구자료를 확인해줘.

기준일은 오늘 날짜로 하고, 전날 이후 새로 등록되었거나 발행일이 오늘인 자료만 알려줘.
각 자료는 다음 형식으로 정리해줘:
- 제목
- 자료 유형
- 발행일
- 저자
- 원문 링크
- 핵심 요약 5줄

신규 자료가 없으면 "오늘 신규 KDI 연구자료는 없습니다."라고 알려줘.
```
