"""7차 실사 — 「준거가 없다」고 적힌 (d) 상수 7개의 근거 탐색을 재현한다.

읽기 전용이다. 제품 코드도 계약 파일도 건드리지 않고, 네트워크에서 원문만 받아
FINDINGS-7.md 가 인용한 문장이 실제로 그 자리에 있는지 확인한다.

    python docs/engineering/diligence/scripts/source_probe.py

각 줄은 [출처 · HTTP 상태 · 바이트 · 검사어 → 적중 수] 다.
적중 0 은 실패가 아니라 결과일 수 있다 — 「그 문서에 그 말이 없다」가 곧 근거인
행이 있기 때문이다(가계금융복지조사의 '상환비율' 0건, data.go.kr 의 '타임아웃' 0건).

의존성: httpx, PyMuPDF(fitz). 저장소의 backend 개발환경에 이미 들어 있다.
"""

from __future__ import annotations

import io
import re
import sys

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"}

# (표시명, URL, [검사어])  — 검사어는 FINDINGS-7.md 가 인용한 문장의 고유 조각이다.
PROBES: list[tuple[str, str, list[str]]] = [
    (
        "감정평가에 관한 규칙 (법제처 DRF)",
        "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&MST=254883&type=XML",
        ["적정한 실거래가", "도시지역", "3년 이내", "5년 이내"],
    ),
    (
        "주택법 (법제처 DRF)",
        "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&LM=%EC%A3%BC%ED%83%9D%EB%B2%95&type=XML",
        ["국민주택규모", "85제곱미터"],
    ),
    (
        "은행업감독규정 (금융위 고시, 법제처 DRF)",
        "https://www.law.go.kr/DRF/lawService.do?OC=test&target=admrul&ID=2100000276094&type=XML",
        ["총부채상환비율", "총부채원리금상환비율", "연간 소득", "세후", "실수령"],
    ),
    (
        "은행업감독업무시행세칙 (금감원장 세칙, 법제처 DRF)",
        "https://www.law.go.kr/DRF/lawService.do?OC=test&target=admrul&ID=2200000108789&type=XML",
        ["연소득의 산정", "근로소득원천징수영수증", "급여입금통장", "실수령"],
    ),
    (
        "국토교통부_아파트 매매 실거래가 자료 (공공데이터포털)",
        "https://www.data.go.kr/data/15126469/openapi.do",
        ["신청 가능 트래픽", "초당 호출 허용량", "일일 호출 허용량", "타임아웃", "재시도 횟수"],
    ),
    (
        "공동주택 실거래가격지수 통계정보 (한국부동산원)",
        "https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?mi=10337&cntntsId=1193&statId=S231520283",
        ["계약월기준", "동일 주택", "반복매매모형", "층그룹", "규모별"],
    ),
]

# 보도자료 PDF 는 본문 추출까지 해야 「없다」를 말할 수 있다.
PDF_PROBE = (
    "2024년 가계금융복지조사 결과 보도자료 (국가데이터처)",
    "https://mods.go.kr/boardDownload.es?bid=215&list_no=434107&seq=4",
    "https://mods.go.kr/board.es?mid=a10301010000&bid=215&act=view&list_no=434107",
    ["처분가능소득", "원리금상환액", "상환비율", "DSR", "부채/자산", "금융부채/저축액"],
)


def probe(name: str, url: str, needles: list[str], *, referer: str | None = None) -> str:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=90.0) as client:
            res = client.get(url)
    except Exception as exc:  # 접근 실패는 실패라고 적는다
        return f"[FAIL] {name}\n        {type(exc).__name__}: {exc}\n        {url}"
    body = res.text
    hits = "  ".join(f"{n}={len(re.findall(re.escape(n), body))}" for n in needles)
    return f"[{res.status_code}] {name}  ({len(res.content):,} bytes)\n        {hits}\n        {url}"


def probe_pdf(name: str, url: str, referer: str, needles: list[str]) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return f"[SKIP] {name} — PyMuPDF 미설치"
    headers = dict(HEADERS, Referer=referer)
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=180.0) as client:
            res = client.get(url)
        doc = fitz.open(stream=io.BytesIO(res.content), filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        return f"[FAIL] {name}\n        {type(exc).__name__}: {exc}\n        {url}"
    hits = "  ".join(f"{n}={len(re.findall(re.escape(n), text))}" for n in needles)
    return (
        f"[{res.status_code}] {name}  ({len(res.content):,} bytes / {doc.page_count}면 / "
        f"{len(text):,}자)\n        {hits}\n        {url}"
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("7차 실사 원문 재확인 — 읽기 전용\n")
    for name, url, needles in PROBES:
        print(probe(name, url, needles))
    print(probe_pdf(*PDF_PROBE))
    print(
        "\n주: 적중 0 이 결론인 행 —\n"
        "  · 가계금융복지조사 보도자료의 '상환비율' · 'DSR' 0건\n"
        "    -> 세후(처분가능소득) 분모의 상환액 **비율**은 공표되지 않는다.\n"
        "  · data.go.kr 의 '타임아웃' · '재시도 횟수' 0건\n"
        "    -> 요청 대기시간과 재시도 횟수에 공표 준거가 없다.\n"
        "  · 은행업감독규정의 '세후' · '실수령' 0건\n"
        "    -> DSR·DTI 는 세후 월소득 분모를 알지 못한다.\n"
        "적중이 결론인 행 —\n"
        "  · 부동산원의 '계약월기준' · '동일 주택'\n"
        "    -> 집계 기간과 면적 짝짓기에 **공표된 규약이 있다**(FINDINGS-7 D7-3 · D7-4)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
