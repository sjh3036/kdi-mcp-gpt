"""MCP server: 국가계약법 기반 공사·물품·용역 견적서 자문 에이전트.

근거 법령: 국가를 당사자로 하는 계약에 관한 법률(이하 "법"), 같은 법 시행령(이하 "영"),
같은 법 시행규칙(이하 "규칙"). 계약방법 및 견적서 제출 기준에 관한 하드코딩된 금액은
법제처 국가법령정보센터 조회(조회기준일 2026-07-05, 법 시행일 20260611 / 영 시행일
20260603 / 규칙 시행일 20260102) 결과로 검증했다. 개정으로 금액·조문이 바뀔 수 있으므로
`fetch_article` 도구로 항상 최신 원문을 재확인할 것.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("estimate-advisor-mcp")
logging.getLogger("httpx").setLevel(logging.WARNING)

LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
LAW_OC = os.getenv("LAW_OC", "").strip()
LAW_VERIFY_SSL = os.getenv("LAW_VERIFY_SSL", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}

LawTier = Literal["법", "시행령", "시행규칙"]

LAW_NAMES: dict[LawTier, str] = {
    "법": "국가를 당사자로 하는 계약에 관한 법률",
    "시행령": "국가를 당사자로 하는 계약에 관한 법률 시행령",
    "시행규칙": "국가를 당사자로 하는 계약에 관한 법률 시행규칙",
}

ContractType = Literal[
    "공사_일반",
    "공사_전문",
    "공사_기타법령",
    "물품_제조",
    "물품_구매임차",
    "용역",
    "재산_매각매입",
    "임대차_기타",
]

CONTRACT_TYPE_LABELS: dict[ContractType, str] = {
    "공사_일반": "건설산업기본법상 공사(전문공사 제외)",
    "공사_전문": "건설산업기본법상 전문공사",
    "공사_기타법령": "그 밖의 공사 관련 법령에 따른 공사",
    "물품_제조": "물품 제조 계약",
    "물품_구매임차": "물품 구매·임차 계약",
    "용역": "용역 계약",
    "재산_매각매입": "재산의 매각·매입 계약",
    "임대차_기타": "공사·물품·용역이 아닌 임대차 계약",
}

# 계약방법(지명경쟁/수의계약) 금액 기준. 단위: 원.
# 근거: 영 제23조제1항(지명경쟁), 제26조제1항제5호가목(수의계약).
CONTRACT_METHOD_RULES: dict[ContractType, dict[str, Any]] = {
    "공사_일반": {
        "designated_limit": 400_000_000,
        "designated_basis": "영 제23조제1항제2호",
        "negotiated_limit": 400_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목1)",
    },
    "공사_전문": {
        "designated_limit": 200_000_000,
        "designated_basis": "영 제23조제1항제2호",
        "negotiated_limit": 200_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목1)",
    },
    "공사_기타법령": {
        "designated_limit": 160_000_000,
        "designated_basis": "영 제23조제1항제2호",
        "negotiated_limit": 160_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목1)",
    },
    "물품_제조": {
        "designated_limit": 100_000_000,
        "designated_basis": "영 제23조제1항제2호",
        "negotiated_limit": 20_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목2)",
    },
    "물품_구매임차": {
        "designated_limit": 50_000_000,
        "designated_basis": "영 제23조제1항제5호",
        "negotiated_limit": 20_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목2)",
    },
    "용역": {
        "designated_limit": 50_000_000,
        "designated_basis": "영 제23조제1항제5호",
        "negotiated_limit": 20_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목2)",
    },
    "재산_매각매입": {
        "designated_limit": 50_000_000,
        "designated_basis": "영 제23조제1항제3호",
        "negotiated_limit": None,
        "negotiated_basis": None,
    },
    "임대차_기타": {
        "designated_limit": 50_000_000,
        "designated_basis": "영 제23조제1항제4호",
        "negotiated_limit": 50_000_000,
        "negotiated_basis": "영 제26조제1항제5호가목6)",
    },
}

# 물품·용역 계약에서 상한이 1억원까지 확대되는 특례 대상 (영 제26조제1항제5호가목3)·4)).
EXTENDED_NEGOTIATED_LIMIT = 100_000_000
EXTENDED_NEGOTIATED_TYPES: set[ContractType] = {"물품_제조", "물품_구매임차", "용역"}

BidderCategory = Literal["일반", "소기업_소상공인", "청년창업기업", "특수지식_학술연구등"]

BIDDER_CATEGORY_BASIS: dict[BidderCategory, str | None] = {
    "일반": None,
    "소기업_소상공인": "영 제26조제1항제5호가목3) (추정가격 2천만원 초과 1억원 이하)",
    "청년창업기업": "영 제26조제1항제5호가목7) (추정가격 5천만원 이하)",
    "특수지식_학술연구등": "영 제26조제1항제5호가목4) (학술연구·원가계산·건설기술 등, 추정가격 2천만원 초과 1억원 이하)",
}

# 입찰자 요건별 수의계약 상한. 단위: 원. 0이면 금액 특례 없음.
# 소기업·소상공인(가목3)과 특수지식(가목4)은 1억원 이하, 청년창업기업(가목7)은 5천만원 이하.
BIDDER_CATEGORY_NEGOTIATED_LIMIT: dict[BidderCategory, int] = {
    "일반": 0,
    "소기업_소상공인": 100_000_000,
    "청년창업기업": 50_000_000,
    "특수지식_학술연구등": 100_000_000,
}

# 1인 견적으로 충분한 무조건적 사유(금액과 무관). 영 제30조제1항제1호.
UNCONDITIONAL_SINGLE_QUOTATION_REASONS = {
    "긴급_재해_비상": "영 제26조제1항제1호가목",
    "보안_국가안전보장": "영 제26조제1항제1호나목",
    "경쟁불성립_특정인기술": "영 제26조제1항제2호",
    "재외공관_현지조달": "영 제26조제1항제5호마목",
    "혁신제품": "영 제26조제1항제5호사목",
    "디지털서비스몰": "영 제26조제1항제5호아목",
}

SingleQuotationReason = Literal[
    "해당없음",
    "긴급_재해_비상",
    "보안_국가안전보장",
    "경쟁불성립_특정인기술",
    "재외공관_현지조달",
    "혁신제품",
    "디지털서비스몰",
]


class ContractMethodAdvice(BaseModel):
    contract_type: str
    contract_type_label: str
    estimated_price_krw: int
    general_competition_available: bool = True
    general_competition_basis: str = "법 제7조제1항 본문 (일반경쟁이 원칙)"
    designated_competition_available: bool
    designated_competition_basis: str | None = None
    negotiated_contract_available: bool
    negotiated_contract_basis: str | None = None
    notes: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "금액 기준은 개정될 수 있으므로 fetch_article로 최신 원문을 반드시 재확인할 것."
    )


class QuotationAdvice(BaseModel):
    contract_type: str
    contract_type_label: str
    estimated_price_krw: int
    negotiated_contract_available: bool
    required_quotations: str
    single_quotation_allowed: bool
    single_quotation_basis: str | None = None
    e_procurement_required: bool
    e_procurement_basis: str = "영 제30조제2항"
    e_procurement_exception_note: str = (
        "학술연구용역, 신선도가 중요한 농·수산물·음식물 구입 등은 규칙 제33조제1항에 따라 "
        "전자조달시스템 이용이 면제될 수 있음"
    )
    quotation_may_be_omitted: bool
    omission_basis: str | None = None
    region_restriction_allowed: bool = True
    region_restriction_basis: str = "규칙 제33조제2항"
    re_quotation_rule: str = (
        "제출된 견적가격이 예정가격 범위에 포함되지 않는 등 계약상대자를 결정할 수 없는 "
        "경우에는 다시 견적서를 제출받아야 함 (영 제30조제6항)"
    )
    notes: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "금액 기준은 개정될 수 있으므로 fetch_article로 최신 원문을 반드시 재확인할 것."
    )


class ArticleResult(BaseModel):
    law_tier: str
    law_name: str
    article: str
    title: str
    text: str
    url: str


class SearchHit(BaseModel):
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    results: list[SearchHit]


def _price_limit_ok(limit: int | None, price: int) -> bool:
    return limit is not None and price <= limit


def advise_contract_method_logic(
    contract_type: ContractType, estimated_price_krw: int
) -> ContractMethodAdvice:
    if estimated_price_krw < 0:
        raise ValueError("estimated_price_krw must be zero or positive")

    rule = CONTRACT_METHOD_RULES[contract_type]
    designated_ok = _price_limit_ok(rule["designated_limit"], estimated_price_krw)
    negotiated_ok = _price_limit_ok(rule["negotiated_limit"], estimated_price_krw)

    notes: list[str] = []
    if contract_type in EXTENDED_NEGOTIATED_TYPES and not negotiated_ok:
        if estimated_price_krw <= EXTENDED_NEGOTIATED_LIMIT:
            notes.append(
                "추정가격이 2천만원을 초과하지만 소기업·소상공인(영 제26조제1항제5호가목3), "
                "1억원 이하), 학술연구·원가계산·건설기술 등 특수지식(같은 호 가목4), 1억원 "
                "이하), 청년창업기업(같은 호 가목7), 5천만원 이하) 등 상대방 요건을 충족하면 "
                "예외적으로 수의계약이 가능할 수 있음. bidder_category 인자로 재확인할 것."
            )

    return ContractMethodAdvice(
        contract_type=contract_type,
        contract_type_label=CONTRACT_TYPE_LABELS[contract_type],
        estimated_price_krw=estimated_price_krw,
        designated_competition_available=designated_ok,
        designated_competition_basis=rule["designated_basis"] if designated_ok else None,
        negotiated_contract_available=negotiated_ok,
        negotiated_contract_basis=rule["negotiated_basis"] if negotiated_ok else None,
        notes=notes,
    )


def advise_quotation_logic(
    contract_type: ContractType,
    estimated_price_krw: int,
    bidder_category: BidderCategory = "일반",
    single_quotation_reason: SingleQuotationReason = "해당없음",
) -> QuotationAdvice:
    if estimated_price_krw < 0:
        raise ValueError("estimated_price_krw must be zero or positive")

    method = advise_contract_method_logic(contract_type, estimated_price_krw)
    notes: list[str] = list(method.notes)

    # 입찰자 요건 특례(가목3)·4)·7))는 물품·용역 계약에만, 각 요건별 상한 이하에서만 적용된다.
    category_limit = BIDDER_CATEGORY_NEGOTIATED_LIMIT[bidder_category]
    bidder_special_available = (
        contract_type in EXTENDED_NEGOTIATED_TYPES
        and bidder_category != "일반"
        and estimated_price_krw <= category_limit
    )
    # 긴급·재해, 경쟁불성립 등 무조건적 사유는 금액과 무관하게 수의계약이 성립한다.
    unconditional_reason = single_quotation_reason != "해당없음"

    negotiated_available = (
        method.negotiated_contract_available
        or bidder_special_available
        or unconditional_reason
    )
    if not method.negotiated_contract_available and bidder_special_available:
        notes.append(f"{bidder_category} 특례({BIDDER_CATEGORY_BASIS[bidder_category]})로 수의계약 가능")
    if not method.negotiated_contract_available and unconditional_reason:
        notes.append(
            f"금액 한도와 무관한 수의계약 사유({UNCONDITIONAL_SINGLE_QUOTATION_REASONS[single_quotation_reason]})에 "
            "해당하여 수의계약 가능"
        )

    if not negotiated_available:
        return QuotationAdvice(
            contract_type=contract_type,
            contract_type_label=CONTRACT_TYPE_LABELS[contract_type],
            estimated_price_krw=estimated_price_krw,
            negotiated_contract_available=False,
            required_quotations="해당없음 (수의계약 요건 미충족 — 일반경쟁 또는 지명경쟁으로 진행)",
            single_quotation_allowed=False,
            e_procurement_required=False,
            quotation_may_be_omitted=False,
            notes=notes
            + ["추정가격이 수의계약 한도를 초과하므로 견적서가 아닌 입찰 절차(법 제7조·제8조)를 따라야 함"],
        )

    # 2천만원 기준 (특례 대상자는 5천만원). 영 제30조제1항제2호.
    amount_threshold = 20_000_000
    if bidder_category in {"청년창업기업"}:
        amount_threshold = 50_000_000
        notes.append(
            "청년창업기업과의 계약은 영 제30조제1항제2호 단서 및 같은 항 제1호(가목7) 인용)에 "
            "따라 1인 견적 허용 범위가 5천만원까지 확대됨"
        )

    single_allowed = False
    single_basis: str | None = None
    if single_quotation_reason != "해당없음":
        single_allowed = True
        single_basis = f"영 제30조제1항제1호 (인용: {UNCONDITIONAL_SINGLE_QUOTATION_REASONS[single_quotation_reason]})"
    elif estimated_price_krw <= amount_threshold:
        single_allowed = True
        single_basis = f"영 제30조제1항제2호 (추정가격 {amount_threshold:,}원 이하)"
    else:
        notes.append(
            "원칙적으로 2인 이상으로부터 견적서를 받아야 함 (영 제30조제1항 본문). 다만 나라장터로 "
            "재공고해도 응찰자가 1인만 예상되는 경우는 같은 항 제3호에 따라 1인 견적이 가능할 수 있음"
        )

    e_procurement_required = estimated_price_krw > amount_threshold
    e_procurement_note = None
    if e_procurement_required:
        e_procurement_note = (
            f"추정가격이 {amount_threshold:,}원을 초과하므로 원칙적으로 전자조달시스템(나라장터)을 "
            "통해 견적서를 제출받아야 함 (영 제30조제2항). 다만 규칙 제33조제1항의 학술연구용역, "
            "신선식품 구입 등 사유가 있으면 예외."
        )
        notes.append(e_procurement_note)

    quotation_may_be_omitted = False
    omission_basis = None
    if contract_type in {"물품_구매임차", "용역"} and estimated_price_krw < 2_000_000:
        quotation_may_be_omitted = True
        omission_basis = "규칙 제33조제3항제2호 (추정가격 200만원 미만 물품 제조·구매·임차·용역계약)"
        notes.append("전기·가스·수도 등 공급계약도 규칙 제33조제3항제1호에 따라 견적서 제출이 생략될 수 있음")

    return QuotationAdvice(
        contract_type=contract_type,
        contract_type_label=CONTRACT_TYPE_LABELS[contract_type],
        estimated_price_krw=estimated_price_krw,
        negotiated_contract_available=True,
        required_quotations="1인 이상" if single_allowed else "2인 이상",
        single_quotation_allowed=single_allowed,
        single_quotation_basis=single_basis,
        e_procurement_required=e_procurement_required,
        quotation_may_be_omitted=quotation_may_be_omitted,
        omission_basis=omission_basis,
        notes=notes,
    )


async def _law_search(query: str, *, display: int = 20) -> list[dict[str, Any]]:
    if not LAW_OC:
        raise RuntimeError("LAW_OC is not configured")

    params = {
        "OC": LAW_OC,
        "target": "law",
        "type": "JSON",
        "query": query,
        "display": str(display),
    }
    async with httpx.AsyncClient(timeout=20.0, verify=LAW_VERIFY_SSL) as client:
        response = await client.get(LAW_SEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    container = payload.get("LawSearch", payload)
    laws = container.get("law", [])
    if isinstance(laws, dict):
        laws = [laws]
    return [item for item in laws if isinstance(item, dict)]


async def _resolve_current_law(law_tier: LawTier) -> dict[str, Any]:
    law_name = LAW_NAMES[law_tier]
    hits = await _law_search(law_name, display=10)
    for hit in hits:
        name = hit.get("법령명한글") or hit.get("법령명") or ""
        if name.strip() == law_name:
            return hit
    if hits:
        return hits[0]
    raise ValueError(f"법령을 찾을 수 없음: {law_name}")


def _extract_article_text(payload: dict[str, Any], article: str) -> tuple[str, str]:
    law_body = payload.get("법령", payload)
    jo_container = law_body.get("조문", {})
    units = jo_container.get("조문단위", []) if isinstance(jo_container, dict) else jo_container
    if isinstance(units, dict):
        units = [units]

    article_digits = "".join(ch for ch in article if ch.isdigit())
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_no = str(unit.get("조문번호", "")).strip()
        if unit_no == article_digits or unit_no == article:
            title = str(unit.get("조문제목", "")).strip()
            content = unit.get("조문내용", "")
            if isinstance(content, list):
                content = "\n".join(str(part) for part in content)
            return title, str(content).strip()

    raise ValueError(f"조문을 찾을 수 없음: {article}")


async def fetch_article_logic(law_tier: LawTier, article: str) -> ArticleResult:
    current = await _resolve_current_law(law_tier)
    mst = current.get("법령일련번호") or current.get("MST")
    law_id = current.get("법령ID") or current.get("법령ID값")
    if not mst:
        raise ValueError(f"법령일련번호를 확인할 수 없음: {law_tier}")

    params = {
        "OC": LAW_OC,
        "target": "law",
        "type": "JSON",
        "MST": str(mst),
        "JO": article,
    }
    async with httpx.AsyncClient(timeout=20.0, verify=LAW_VERIFY_SSL) as client:
        response = await client.get(LAW_SERVICE_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    title, text = _extract_article_text(payload, article)
    url = f"https://www.law.go.kr/DRF/lawService.do?OC={LAW_OC}&target=law&MST={mst}&type=HTML&JO={article}"
    return ArticleResult(
        law_tier=law_tier,
        law_name=LAW_NAMES[law_tier],
        article=article,
        title=title,
        text=text,
        url=url,
    )


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="국가계약법 견적 자문",
        instructions=(
            "국가를 당사자로 하는 계약에 관한 법률 체계(법·시행령·시행규칙)를 근거로 공사·물품·"
            "용역 견적서 작성·제출에 관해 자문한다. advise_contract_method로 계약방법(일반/지명/"
            "수의)을 먼저 판단하고, advise_quotation으로 견적서 제출 인원·전자조달시스템 의무·"
            "생략 가능 여부를 확인한다. 정확한 조문 원문은 fetch_article로 재확인할 것 — 이 서버의 "
            "금액 기준은 특정 조회 시점 기준으로 하드코딩되어 있어 개정 시 달라질 수 있다."
        ),
    )

    @mcp.tool(output_schema=ContractMethodAdvice.model_json_schema())
    async def advise_contract_method(
        contract_type: ContractType, estimated_price_krw: int
    ) -> ContractMethodAdvice:
        """추정가격과 계약 유형(공사/물품/용역 등)을 바탕으로 일반경쟁·지명경쟁·수의계약 중
        어떤 계약방법을 선택할 수 있는지와 그 근거 조문을 안내한다."""
        return advise_contract_method_logic(contract_type, estimated_price_krw)

    @mcp.tool(output_schema=QuotationAdvice.model_json_schema())
    async def advise_quotation(
        contract_type: ContractType,
        estimated_price_krw: int,
        bidder_category: BidderCategory = "일반",
        single_quotation_reason: SingleQuotationReason = "해당없음",
    ) -> QuotationAdvice:
        """수의계약으로 진행할 때 견적서를 몇 인 이상 받아야 하는지, 전자조달시스템(나라장터)
        이용이 의무인지, 견적서 제출을 생략할 수 있는지를 국가계약법 시행령 제30조 및 시행규칙
        제33조를 근거로 안내한다."""
        return advise_quotation_logic(
            contract_type, estimated_price_krw, bidder_category, single_quotation_reason
        )

    @mcp.tool(output_schema=ArticleResult.model_json_schema())
    async def fetch_article(law_tier: LawTier, article: str) -> ArticleResult:
        """국가법령정보센터(law.go.kr)에서 국가계약법/시행령/시행규칙의 현행 조문 원문을
        실시간으로 조회한다. article 예: '제30조'. LAW_OC 환경변수(law.go.kr Open API 사용자
        이메일 ID) 설정이 필요하다."""
        return await fetch_article_logic(law_tier, article)

    @mcp.tool(output_schema=SearchOutput.model_json_schema())
    async def search(query: str) -> SearchOutput:
        """국가계약법 체계(법/시행령/시행규칙) 내에서 키워드로 법령을 검색한다. law.go.kr Open
        API(LAW_OC)가 필요하다."""
        hits = await _law_search(query)
        results = [
            SearchHit(
                id=str(hit.get("법령ID", hit.get("법령일련번호", ""))),
                title=str(hit.get("법령명한글", hit.get("법령명", ""))),
                url=str(hit.get("법령상세링크", "")) or "https://www.law.go.kr/",
            )
            for hit in hits
        ]
        return SearchOutput(results=results)

    return mcp


def main() -> None:
    port = int(os.getenv("PORT", "8001"))
    server = create_server()

    if not LAW_OC:
        logger.warning(
            "LAW_OC is not set — fetch_article and search will fail until it is configured"
        )

    logger.info("Starting estimate-advisor MCP server on 0.0.0.0:%s", port)
    server.run(transport="sse", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
