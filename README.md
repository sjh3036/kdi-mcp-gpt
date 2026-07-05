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

---

# Estimate Advisor MCP Server (`estimate_advisor_server.py`)

A second, independent MCP server that advises on 공사·물품·용역 견적서 (construction /
goods / services quotations) under the **국가를 당사자로 하는 계약에 관한 법률**
(Act on Contracts to Which the State Is a Party) and its 시행령/시행규칙.

## What It Exposes

- `advise_contract_method`: Given a contract type and 추정가격(estimated price, KRW),
  reports whether 일반경쟁/지명경쟁/수의계약 is available and the article basis
  (영 제23조, 제26조).
- `advise_quotation`: For negotiated contracts (수의계약), reports how many
  quotations are required (1인/2인 이상), whether the e-procurement system
  (나라장터) is mandatory, whether the quotation can be omitted, and the
  re-quotation rule — based on 영 제30조 and 규칙 제33조.
- `fetch_article`: Fetches the current official article text live from
  law.go.kr (법/시행령/시행규칙), so the amounts hardcoded in this server can be
  cross-checked against the latest amendment.
- `search`: Keyword search across the 국가계약법 law family via law.go.kr.

**Important:** The KRW thresholds in this server were verified against the law
in force as of the article citations in the code, but the enforcement decree
and rule are amended periodically. Always cross-check with `fetch_article`
before relying on an answer for an actual procurement decision.

## Local Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `LAW_OC` to your law.go.kr Open API user ID (register at
https://open.law.go.kr — it's free). `fetch_article` and `search` need it;
`advise_contract_method` and `advise_quotation` work without it since their
rules are embedded in the code.

Run:

```bash
python estimate_advisor_server.py
```

The MCP endpoint is `http://localhost:8001/sse/` (override the port with `PORT`).

## Deploy Notes

Set these environment variables in your hosting provider:

- `LAW_OC`: your law.go.kr Open API user ID.
- `LAW_VERIFY_SSL`: keep `true` in production.
- `PORT`: usually provided by the host.

`render.yaml` defines this as a second Render web service
(`estimate-advisor-mcp-server`) alongside the KDI server.
