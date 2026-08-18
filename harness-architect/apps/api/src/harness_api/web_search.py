"""웹검색 — 스튜디오 에이전트가 실존 도구/API/리소스를 근거로 삼도록.

Tavily(에이전트용 검색 API)를 httpx 로 호출한다. 키는 app_settings(search_key, 암호화)에서 오고,
없으면 검색은 비활성(에이전트에 '미설정'을 알려 키 없이 진행). 결과는 LLM 이 읽기 좋은 짧은 스니펫.
"""

from __future__ import annotations

import httpx

_ENDPOINT = "https://api.tavily.com/search"


def web_search(api_key: str, query: str, *, max_results: int = 5) -> str:
    """검색 결과를 LLM 에게 줄 텍스트로. 키 없으면 안내 문자열, 실패해도 예외 대신 요약 반환."""
    if not api_key:
        return "웹검색 미설정(설정에서 검색 키 등록 필요) — 검색 없이 아는 선에서 진행하라."
    q = query.strip()
    if not q:
        return "빈 검색어."
    try:
        resp = httpx.post(
            _ENDPOINT,
            json={
                "api_key": api_key,
                "query": q,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — 검색 실패는 치명적 아님(에이전트가 아는 선에서 진행)
        return f"웹검색 실패({type(exc).__name__}) — 검색 없이 진행하라."

    lines: list[str] = []
    answer = str(data.get("answer") or "").strip()
    if answer:
        lines.append(f"요약: {answer[:400]}")
    for r in data.get("results", [])[:max_results]:
        title = str(r.get("title") or "")[:100]
        url = str(r.get("url") or "")
        content = str(r.get("content") or "")[:200]
        lines.append(f"- {title} ({url}) — {content}")
    return "\n".join(lines) or "검색 결과 없음."
