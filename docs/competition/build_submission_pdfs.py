"""Build the two preliminary-round PDFs from the official form headings.

The official HWPX files are layout references, not runtime dependencies. Their
required headings and order are preserved here so the generated PDFs remain
portable and reproducible. Personal participant data is loaded from the ignored
``submission_profile.local.json`` file or an explicit ``--profile`` path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO_ROOT / "output" / "pdf"
DEFAULT_PROFILE = HERE / "submission_profile.local.json"
EXAMPLE_PROFILE = HERE / "submission_profile.example.json"
DEFAULT_EVIDENCE = REPO_ROOT / "output" / "evidence"

PLACEHOLDER = "__운영자_실명_입력__"

INK = colors.HexColor("#1C1A17")
INK_2 = colors.HexColor("#4A423A")
INK_3 = colors.HexColor("#655F53")
ACCENT = colors.HexColor("#FFB800")
ACCENT_DEEP = colors.HexColor("#8A6200")
ACCENT_WASH = colors.HexColor("#FFF7D6")
PANEL = colors.HexColor("#F4F2ED")
LINE = colors.HexColor("#CFC9BE")
WHITE = colors.white
CRITICAL = colors.HexColor("#A82828")


def register_fonts() -> tuple[str, str]:
    candidates = [
        (Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")),
        (Path("C:/Windows/Fonts/NotoSansKR-VF.ttf"), Path("C:/Windows/Fonts/NotoSansKR-VF.ttf")),
    ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("HC-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("HC-Bold", str(bold)))
            pdfmetrics.registerFontFamily(
                "HC-Regular", normal="HC-Regular", bold="HC-Bold",
                italic="HC-Regular", boldItalic="HC-Bold",
            )
            return "HC-Regular", "HC-Bold"
    raise RuntimeError(
        "Korean font not found. Install Malgun Gothic or Noto Sans KR, or set up "
        "an equivalent font in build_submission_pdfs.py."
    )


FONT, FONT_BOLD = register_fonts()


def load_profile(path: Path | None) -> dict[str, str]:
    source = path or (DEFAULT_PROFILE if DEFAULT_PROFILE.is_file() else EXAMPLE_PROFILE)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return {
        "team_name": str(payload.get("team_name") or "Home_Compass").strip(),
        "member_names": str(payload.get("member_names") or PLACEHOLDER).strip(),
    }


def validate_profile(profile: dict[str, str], strict: bool) -> None:
    missing = [key for key, value in profile.items() if not value or "__운영자_" in value]
    if strict and missing:
        raise SystemExit(
            "Operator-owned submission fields are incomplete: " + ", ".join(missing)
            + f". Copy {EXAMPLE_PROFILE.name} to {DEFAULT_PROFILE.name} and fill them."
        )


def styles():
    sheet = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "HC-Title", parent=sheet["Title"], fontName=FONT_BOLD, fontSize=19,
            leading=25, textColor=INK, alignment=TA_LEFT, spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "HC-Section", parent=sheet["Heading2"], fontName=FONT_BOLD, fontSize=11.2,
            leading=15, textColor=INK, spaceAfter=0,
        ),
        "body": ParagraphStyle(
            "HC-Body", parent=sheet["BodyText"], fontName=FONT, fontSize=9.2,
            leading=14.2, textColor=INK_2, wordWrap="CJK", spaceAfter=4,
        ),
        "body_bold": ParagraphStyle(
            "HC-Body-Bold", parent=sheet["BodyText"], fontName=FONT_BOLD, fontSize=9.2,
            leading=14.2, textColor=INK, wordWrap="CJK", spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "HC-Small", parent=sheet["BodyText"], fontName=FONT, fontSize=7.7,
            leading=11.2, textColor=INK_3, wordWrap="CJK",
        ),
        "cell": ParagraphStyle(
            "HC-Cell", parent=sheet["BodyText"], fontName=FONT, fontSize=8.2,
            leading=11.5, textColor=INK_2, wordWrap="CJK",
        ),
        "cell_head": ParagraphStyle(
            "HC-Cell-Head", parent=sheet["BodyText"], fontName=FONT_BOLD, fontSize=8.2,
            leading=11.5, textColor=INK, wordWrap="CJK", alignment=TA_CENTER,
        ),
        "cell_head_white": ParagraphStyle(
            "HC-Cell-Head-White", parent=sheet["BodyText"], fontName=FONT_BOLD,
            fontSize=8.2, leading=11.5, textColor=WHITE, wordWrap="CJK",
            alignment=TA_CENTER,
        ),
        "callout": ParagraphStyle(
            "HC-Callout", parent=sheet["BodyText"], fontName=FONT_BOLD, fontSize=9.3,
            leading=14.5, textColor=INK, wordWrap="CJK",
        ),
        "placeholder": ParagraphStyle(
            "HC-Placeholder", parent=sheet["BodyText"], fontName=FONT_BOLD, fontSize=8.5,
            leading=12, textColor=CRITICAL, wordWrap="CJK",
        ),
    }


ST = styles()


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, ST[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(text, ST["body"], bulletText="•")


def section_block(number: str, title: str, items: list, note: str | None = None):
    head = Table(
        [[para(f"{number}. {title}", "section")]],
        colWidths=[174 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PANEL),
            ("BOX", (0, 0), (-1, -1), 0.65, INK),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    body = []
    if note:
        body.append(para(note, "small"))
        body.append(Spacer(1, 2 * mm))
    for item in items:
        if isinstance(item, str):
            body.append(bullet(item))
        else:
            body.append(item)
    return [head, Spacer(1, 3 * mm), *body, Spacer(1, 4 * mm)]


def identity_header(attachment: str, title: str, profile: dict[str, str]):
    title_table = Table(
        [[para(f"첨부 {attachment}", "body_bold"), para(title, "title")]],
        colWidths=[27 * mm, 147 * mm],
        rowHeights=[15 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (0, 0), 0.8, colors.HexColor("#6D84C4")),
            ("BOX", (1, 0), (1, 0), 0.8, colors.HexColor("#6D84C4")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    member_style = "placeholder" if "__운영자_" in profile["member_names"] else "body"
    identity = Table(
        [
            [para("팀명", "cell_head"), para(profile["team_name"], "body")],
            [para("구성원 성명", "cell_head"), para(profile["member_names"], member_style)],
        ],
        colWidths=[44 * mm, 130 * mm],
        rowHeights=[12 * mm, 12 * mm],
        style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.65, INK),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E3E3E3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]),
    )
    return [title_table, Spacer(1, 4 * mm), identity, Spacer(1, 2 * mm), para("(* 필수항목)", "small"), Spacer(1, 5 * mm)]


def callout(text: str):
    return Table(
        [[para(text, "callout")]],
        colWidths=[174 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ACCENT_WASH),
            ("LINEBEFORE", (0, 0), (0, -1), 4, ACCENT),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E8D591")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]),
    )


def grid_table(headers: list[str], rows: list[list[str]], widths: list[float]):
    data = [[para(h, "cell_head_white") for h in headers]]
    data.extend([[para(cell, "cell") for cell in row] for row in rows])
    return Table(
        data,
        colWidths=[w * mm for w in widths],
        repeatRows=1,
        style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.45, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#FAF9F6")]),
        ]),
    )


def screenshot(path: Path, caption: str, *, width_mm: float = 174, height_mm: float = 98):
    if not path.is_file():
        return []
    img = Image(str(path), width=width_mm * mm, height=height_mm * mm, kind="proportional")
    img.hAlign = "CENTER"
    return [img, Spacer(1, 1.5 * mm), para(caption, "small"), Spacer(1, 4 * mm)]


def evidence_appendix(title: str, items: list[tuple[Path, str]]):
    head = Table(
        [[para(title, "section")]],
        colWidths=[174 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PANEL),
            ("BOX", (0, 0), (-1, -1), 0.65, INK),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    story = [PageBreak(), head, Spacer(1, 4 * mm)]
    for path, caption in items:
        story += screenshot(path, caption, height_mm=72)
    return story


class CompetitionDoc(BaseDocTemplate):
    def __init__(self, filename: Path, doc_label: str):
        super().__init__(
            str(filename), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=18 * mm, bottomMargin=16 * mm,
            title=doc_label, author="Home_Compass", subject="2026 금융 AI Challenge",
            creator="Home_Compass submission builder", invariant=1,
        )
        self.doc_label = doc_label
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates(PageTemplate(id="all", frames=[frame], onPage=self._page))

    def _page(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
        canvas.setFont(FONT, 7.3)
        canvas.setFillColor(INK_3)
        canvas.drawString(18 * mm, 8 * mm, f"Home_Compass | {self.doc_label}")
        canvas.drawRightString(192 * mm, 8 * mm, f"- {doc.page} -")
        canvas.restoreState()


def planning_story(profile: dict[str, str], evidence_dir: Path):
    story = identity_header("1", "2026 금융 AI Challenge 기획서", profile)
    story += section_block("1", "서비스 명칭*", [
        "<b>Home_Compass</b> - 청년 임차 가구가 자신의 소득과 자산으로 감당 가능한 집의 범위를 먼저 판정하고, 전세·월세 비용과 정책 자격을 같은 근거 위에서 비교하는 주거 금융 의사결정 서비스",
    ])
    story += section_block("2", "아이디어 기획 핵심내용(요약)*", [
        "사용자가 나이·가구원·희망지역·소득·자산·부채·주거조건을 입력하면 4개의 결정론적 엔진이 월 주거비 상한, 전월세 5년 총비용, 정책 적격성, 보증금 위험을 한 번에 계산합니다.",
        "생성형 AI는 계산하거나 자격을 임의로 판정하지 않습니다. 엔진 결과를 대화형으로 설명하고, 정책 원문을 기계 판정 규칙 초안으로 변환하는 두 역할만 맡습니다.",
        "모든 결과에는 계산 사유와 데이터 출처·관측시각·검증상태가 붙습니다. 확인되지 않은 값은 숨기지 않고 데이터 등급과 사유로 표시합니다.",
        "정책 원문에서 추출한 규칙은 사람이 원문 근거와 판정 영향도를 확인하고 승인하기 전에는 시민 판정에 반영되지 않습니다.",
    ])
    story.append(callout("핵심 제안: 더 많은 금융상품을 나열하지 않고, 사용자가 지금 감당할 수 있는 주거비와 실행 가능한 다음 행동을 숫자와 근거로 먼저 좁힙니다."))
    story.append(Spacer(1, 5 * mm))
    story += section_block("3", "문제 정의 및 제안 배경*", [
        "<b>문제 1 - 비교 기준의 파편화:</b> 청년 임차인은 월세, 전세대출 이자, 관리비, 보증금의 기회비용을 서로 다른 화면과 단위로 접합니다. 월 납입액만 보면 보증금 부담과 5년 총비용이 가려집니다.",
        "<b>문제 2 - 정책 정보의 잦은 변경:</b> 나이·소득·자산·무주택·지역 조건은 정책마다 다르고 공고문은 비정형 문서입니다. 단순 검색은 '왜 나는 제외되는가'와 '무엇을 추가 확인해야 하는가'를 답하지 못합니다.",
        "<b>문제 3 - 금융 AI의 신뢰 경계:</b> 언어모델이 숫자 계산과 자격 판정까지 수행하면 같은 입력에도 결과가 흔들리고, 틀린 규칙이 다수 사용자에게 전파될 수 있습니다.",
        "<b>대상 고객과 채널:</b> 첫 독립 주거를 준비하거나 계약 갱신을 앞둔 청년 임차 가구를 대상으로 합니다. 사전 탐색은 모바일·웹에서 익명으로 제공하고, 상담원과 정책 운영자는 같은 웹서비스의 역할별 화면에서 근거를 이어받습니다.",
        "<b>제안 배경:</b> 청년에게 필요한 첫 질문은 '어떤 상품이 인기인가'가 아니라 '내가 지금 얼마짜리 집에 살아도 되는가'입니다. 이 질문을 먼저 풀어야 이후의 대출·보증·지원정책 선택이 과도한 차입을 유도하지 않습니다.",
    ])
    story.append(PageBreak())
    story += section_block("4", "서비스 컨셉 및 차별성*", [
        "<b>추천보다 판정:</b> 가처분소득에서 생활비·기존부채·안전버퍼를 차감하고 소득비율 상한과 교차해 월 주거비 상한 및 권장액을 산출합니다. 감당할 수 없는 선택은 인기 상품이어도 권장하지 않습니다.",
        "<b>동일 단위 비교:</b> 전세·반전세·월세를 대출이자, 월세, 관리비, 보증금 기회비용, 보증료를 포함한 5년 총비용(TCO)과 현재가치(NPV), 월 환산비용으로 비교합니다.",
        "<b>설명 가능한 정책 매칭:</b> 적격/조건부/부적격뿐 아니라 조건별 통과·실패·추가확인 사유를 함께 보여 줍니다. 상담원 화면에서는 적용 규칙 버전과 문턱까지 확인할 수 있습니다.",
        "<b>AI 권한 분리:</b> 판정 경로에는 LLM이 없습니다. 런타임 AI는 엔진 숫자를 설명하고, 오프라인 AI는 정책 규칙 초안을 만들지만 사람 승인 전에는 효력이 없습니다.",
        "<b>데이터 정직성:</b> 항목별 출처, 관측시각, 검증상태를 응답까지 전달하고 A-C 등급과 구체적 강등 사유로 노출합니다. 모르는 값을 그럴듯한 기본값으로 감추지 않습니다.",
        "<b>운영까지 포함한 MVP:</b> 정책 원문 수집 → 구조화 추출 → span 검증 → 영향도 비교 → 승인/반려 → 감사이력의 전체 흐름을 관리자 웹 화면에서 제공합니다.",
    ])
    story += section_block("5", "활용 데이터 및 생성형 AI 모델 적용 방안*", [
        "<b>시장 데이터:</b> 국토교통부 아파트 전월세·매매 실거래가 OpenAPI를 지역별로 수집하고, 전세 중위가·월세 보증금·월세·전세가율·전월세전환율을 셀 단위로 도출합니다. 현재 MVP는 서울·경기·부산·대전·대구·광주의 10개 지역을 포함합니다.",
        "<b>정책 데이터:</b> 주택도시기금, HUG, 중앙정부·지자체의 정책 원문을 사용합니다. 원문 라이선스 확인, 출처 메타데이터, 코드포인트 기반 인용 구간을 함께 저장합니다.",
        "<b>모델 상수:</b> 법령·공표통계·시장금리·서비스의 규범적 선택을 구분합니다. 값, 단위, 기준시점, 검증상태를 계약 파일로 관리하고 민감도 분석으로 결과 변화를 점검합니다.",
        "<b>생성형 AI 역할 A - 대화형 설명:</b> OpenAI 또는 Anthropic의 tool/function calling을 이용해 사용자의 자연어 질문을 정해진 엔진 도구로 연결하고, 도구가 반환한 숫자와 근거만 설명합니다. 키가 없거나 호출이 실패하면 결정론적 한국어 템플릿으로 즉시 전환합니다.",
        "<b>생성형 AI 역할 B - 정책 규칙 추출:</b> 공고문을 입력으로 받아 엄격한 JSON 스키마의 RuleDraft를 생성합니다. 원문에 실제 존재하는 인용 구간인지 기계 검증하고, 실패한 초안은 승인할 수 없습니다.",
        "<b>사람 승인 게이트:</b> 규칙관리자는 필드별 원문 근거와 기존 사례의 판정 변화(impact)를 확인한 뒤 승인합니다. 승인·반려·로그인·접근거부는 append-only 감사이력으로 남습니다.",
        "<b>개인정보:</b> 시민 진단의 7개 입력값은 계정 없이 처리되며 저장하지 않습니다. 로그에도 요청 본문을 기록하지 않습니다. 직원 인증은 Argon2id 비밀번호, HttpOnly/Secure/SameSite 쿠키, CSRF 방어를 사용합니다.",
    ])
    story.append(PageBreak())
    story += section_block("6", "기대 효과 및 확장 가능성*", [
        "<b>금융소비자:</b> 감당 가능한 상한을 먼저 확인해 과도한 보증금·대출을 피하고, 서로 다른 전월세 안을 같은 비용 단위로 비교할 수 있습니다. 부적격 사유와 추가확인 조건까지 보여 불필요한 신청 비용을 줄입니다.",
        "<b>상담원:</b> 고객 입력을 다시 해석하지 않고 동일 판정과 근거, 적용 규칙 버전을 확인해 설명 품질을 표준화할 수 있습니다. 이상 데이터는 해당 항목에서 바로 운영자에게 신고합니다.",
        "<b>정책 운영자:</b> 비정형 공고문을 구조화하는 반복 작업을 줄이되, 자동 반영 위험은 사람 승인과 회귀 영향도 검사로 차단합니다. 변경 이력과 실패율을 상태 화면에서 추적합니다.",
        "<b>금융기관 적용:</b> 전세자금대출·보증·주거지원 상담의 사전 진단 레이어로 연결할 수 있습니다. 판정 엔진과 LLM 제공자를 분리해 내부망 모델, 기관별 상품 카탈로그, 외부 DB로 교체 가능합니다.",
        "<b>시장 확대:</b> 청년 임차에서 신혼부부·고령층·장애인 등 포용금융 대상으로 규칙 세트를 확장할 수 있습니다. 주거 외에도 복잡한 자격 요건과 비용 비교가 필요한 정책금융·소상공인 지원에 같은 '추출-승인-집행' 구조를 적용할 수 있습니다.",
        "<b>운영 확장:</b> 현재 10개 지역의 배치 수집을 전국으로 확장하고, PostgreSQL 등 외부 저장소, 비밀관리, 백업, 알림 채널을 연결할 수 있도록 저장소와 설정 경계를 분리했습니다.",
    ])
    story += section_block("7", "구현 완성도·안전장치 및 검증", [
        "<b>작동 범위:</b> 시민용 웹, 규칙관리 웹, FastAPI 백엔드, 18개 HTTP 오퍼레이션, 4개 판정 엔진, 10개 지역, 8개 정책 규칙, 정책 수집·추출·승인·감사 파이프라인을 하나의 동일 오리진 서비스로 구현했습니다.",
        "<b>검증:</b> 제출 준비 시점 기준 자동 테스트 2,276개가 통과했습니다. 단위·통합·계약·프론트/백엔드 동등성·인증·동시성·감사 append-only·기동 스모크를 포함합니다.",
        "<b>장애 대응:</b> LLM 키가 없어도 모든 핵심 판정과 설명 템플릿이 동작합니다. 외부 시장 API 장애 시 승인된 이전 스냅샷을 유지하며, 공개 배포는 단일 worker·영구 SQLite·헬스체크로 구성합니다.",
        "<b>한계 공개:</b> 현재 활성 정책 중 원문 승인을 거치지 않은 시드 규칙과 실거래가로 도출할 수 없는 일부 지역 필드는 데이터 등급 C 사유로 표시합니다. 본 서비스는 금융상품 승인·판매·투자자문이 아닌 의사결정 보조 도구입니다.",
        Spacer(1, 2 * mm),
        grid_table(
            ["검증 축", "현재 구현 증거"],
            [
                ["정확성", "결정론적 엔진·계약 스냅샷·프론트/백엔드 동등성 테스트"],
                ["안전성", "LLM 권한 분리, 승인 전 규칙 차단, append-only 감사"],
                ["운영성", "헬스체크, 시드 멱등성, 영구 저장소, 단일 worker"],
                ["접근성", "익명 핵심 흐름, 390px 모바일·1440px 데스크톱 실브라우저 확인"],
            ],
            [30, 144],
        ),
    ])
    story += [Spacer(1, 2 * mm), para("주요 출처: 국토교통부 실거래가 OpenAPI, 주택도시기금, HUG, KOSIS·한국은행·한국부동산원 공표자료. 세부 URL과 인용 근거는 소스코드의 contracts/ 및 docs/engineering/diligence/에 기록했습니다.", "small")]
    story += evidence_appendix("부록 A. 실제 동작 화면", [
        (evidence_dir / "home_compass_onboarding.png", "[그림 1] 접속 직후 - 입력 항목과 4대 판정 엔진을 한 화면에서 안내"),
        (evidence_dir / "home_compass_dashboard.png", "[그림 2] 익명 진단 결과 - 주거비 상한, 총비용, 정책, 위험도와 데이터 등급을 한 흐름으로 제시"),
    ])
    return story


def feature_story(profile: dict[str, str], evidence_dir: Path):
    story = identity_header("2", "2026 금융 AI Challenge 기능 명세서", profile)
    story += section_block("1", "MVP 구현 범위*", [
        "<b>시민용 익명 진단:</b> 프로필 입력, 감당 가능한 월 주거비 상한·권장액 계산, 전세/반전세/월세 4개 시나리오의 5년 TCO·NPV 비교, 정책 적격성 및 사유, 보증금 위험점수, 데이터 계보·등급을 구현했습니다.",
        "<b>AI 상담:</b> 진단 결과를 바탕으로 자연어 후속 질문에 답합니다. 라이브 LLM 사용 시에도 숫자는 엔진 도구 결과에서만 가져오며, 키 부재·실패 시 결정론적 템플릿으로 동작합니다.",
        "<b>상담원 기능:</b> 로그인한 상담원은 동일 화면에서 규칙 버전·신선도·부적격 문턱을 추가 확인하고 요약본 출력과 데이터 이상 신고를 수행할 수 있습니다.",
        "<b>정책 운영 기능:</b> 원문/추출 초안 대기열, 필드별 인용 근거, 검증 오류, 판정 영향도, 승인·반려·일괄승인, 상태 지표, 신고 큐, 감사이력을 관리자 화면에 구현했습니다.",
        "<b>배포·운영:</b> 동일 오리진 정적 웹+API, 영구 SQLite, 단일 worker, HTTPS 쿠키, 시드 검증, /api/health 헬스체크를 포함한 컨테이너 배포 구성을 제공합니다.",
        "<b>MVP 제외:</b> 대출 승인·청약·계약 체결, 개인신용정보 조회, 사용자 프로필 저장, 전국 전 주택유형의 실시간 시세, 금융기관 내부 상품 API, 외부 알림·백업·상용 모니터링은 구현 범위가 아닙니다.",
    ])
    features = [
        ["F1", "주거지불능력 판정", "가처분소득·생활비·부채·안전버퍼로 월 상한/권장액과 사유 산출", "시민 화면 STEP 02", "완료"],
        ["F2", "전월세 총비용 비교", "4개 시나리오의 대출이자·월세·관리비·기회비용·보증료, TCO/NPV/월 환산 비교", "STEP 03", "완료"],
        ["F3", "정책 적격성", "8개 정책의 적격/조건부/부적격 및 조건별 사유와 금액·금리 범위 표시", "STEP 04", "완료"],
        ["F4", "보증금 위험", "전세가율·보증 가능성·대출비중·보증금 규모·시장여건을 0-100점으로 제시", "STEP 05", "완료"],
        ["F5", "데이터 등급·계보", "판정에 사용한 사실별 출처·관측시각·검증상태와 A-C 등급 사유 표시", "STEP 06", "완료"],
        ["F6", "AI 상담", "엔진 도구 결과만 인용하는 대화형 설명, 라이브 제공자 실패 시 템플릿 폴백", "AI 상담 카드", "완료"],
        ["F7", "상담원 확장", "내부 문턱·버전·신선도 확인, 출력, 항목 기반 이상 신고", "시민 화면 로그인 후", "완료"],
        ["F8", "정책 추출 검토", "원문 span·스키마 검증, 필드 비교, 실패 초안 차단", "/admin/ 초안 상세", "완료"],
        ["F9", "영향도·승인", "승인 전 회귀 프로필의 판정 변화 확인, 단건/일괄 승인·반려", "/admin/ 검토 화면", "완료"],
        ["F10", "감사·상태", "로그인·거부·신고·승인 이력과 배치/실패율/대기시간 지표", "/admin/ 상태·감사", "완료"],
    ]
    story += section_block("2", "주요 기능 목록*", [grid_table(["ID", "기능명", "기능 설명", "관련 화면", "상태"], features, [11, 28, 80, 35, 20])])
    story += section_block("3", "사용자 이용 흐름*", [
        "<b>1) 접속:</b> 제출 탭에 등록된 배포 URL을 Chrome·Edge·Safari 등 최신 브라우저로 엽니다. 시민 기능은 회원가입이나 로그인 없이 사용할 수 있습니다.",
        "<b>2) 입력:</b> 상단의 '예시 프로필 채우기'를 누르거나 왼쪽 패널에서 나이, 가구원 수, 희망지역, 연소득, 월 실수령액, 현금성 자산, 기존 대출 상환액과 주거조건을 입력합니다.",
        "<b>3) 진단:</b> '주거비 진단 시작'을 누르면 STEP 02-06이 차례로 표시됩니다. 권장액과 상한, 4개 시나리오, 정책 판정, 위험요인, 데이터 등급을 확인합니다.",
        "<b>4) 근거 확인:</b> 각 카드의 사유와 출처를 펼쳐 어떤 입력·규칙·데이터가 결과를 만들었는지 확인합니다. 조건부 정책은 추가 서류나 물건별 확인사항을 표시합니다.",
        "<b>5) AI 질문:</b> 하단 AI 상담의 추천 질문을 누르거나 자연어로 질문합니다. 답변 상단 칩에서 라이브 LLM 또는 결정론적 템플릿 모드를 확인할 수 있습니다.",
        "<b>6) 선택 운영 흐름:</b> 운영자가 별도로 제공한 계정이 있는 경우 /admin/에서 정책 초안의 원문 근거와 영향도를 확인하고 승인·반려·감사이력을 검증할 수 있습니다. 시민 핵심 흐름 검증에는 계정이 필요하지 않습니다.",
    ])
    story += screenshot(evidence_dir / "home_compass_onboarding.png", "[그림 1] 접속 직후 화면 - 왼쪽 입력 7개와 오른쪽 4대 판정 엔진을 한 화면에서 안내")
    story.append(PageBreak())
    story += section_block("4", "AI 및 데이터 처리 방식*", [
        "<b>입력:</b> 시민 프로필(나이·가구·지역·소득·자산·부채·주거조건), 자연어 상담 질문, 정책 운영 시 공고문 텍스트와 출처 메타데이터를 받습니다.",
        "<b>결정론적 처리:</b> /api/analyze는 LLM을 호출하지 않습니다. 주거지불능력, TCO/NPV, 정책 적격성, 위험점수를 Python 엔진이 동일 입력에 동일 결과로 계산합니다.",
        "<b>런타임 AI:</b> OpenAI 또는 Anthropic 모델은 허용된 엔진 도구를 호출하고 반환된 결과를 한국어로 설명합니다. 모델은 주거비·금리·정책 자격 숫자를 직접 생성할 권한이 없습니다.",
        "<b>오프라인 추출 AI:</b> 정책 원문을 RuleDraft JSON으로 변환합니다. 필드별 인용 구간이 원문과 일치하는지, 스키마·조건 연산자가 허용 범위인지 검증한 뒤 사람 검토 큐에 둡니다.",
        "<b>출력:</b> 권장/최대 주거비, 4개 시나리오의 비용과 적합도, 정책 상태·사유, 위험점수·요인, 데이터 등급·계보, 자연어 상담 답변을 반환합니다.",
        "<b>데이터 저장:</b> 익명 시민 입력과 질문은 영구 저장하지 않고 요청 로그에도 본문을 남기지 않습니다. 정책 원문·규칙 버전·승인·감사이력은 운영 저장소에 보존합니다.",
        "<b>민감정보:</b> 주민등록번호, 계좌·카드번호, 신용점수, 연락처를 입력받지 않습니다. 소득·자산·부채는 판정에 필요한 최소 금액만 받고 사용자 식별자와 연결하지 않습니다.",
        "<b>실패 처리:</b> LLM 키가 없거나 응답이 실패하면 핵심 판정은 영향 없이 동작하고 상담만 템플릿 모드로 전환됩니다. 외부 시세 API 실패 시 기존 승인 스냅샷을 유지합니다.",
        Spacer(1, 2 * mm),
        grid_table(
            ["경로", "처리 주체", "효력·차단선"],
            [
                ["시민 진단", "Python 결정론 엔진", "즉시 효력 · LLM 호출 없음"],
                ["AI 상담", "도구 호출형 LLM 또는 템플릿", "엔진 반환값만 설명 · 실패 시 폴백"],
                ["정책 추출", "구조화 출력 LLM", "초안만 생성 · span/스키마 실패 시 차단"],
                ["정책 반영", "규칙관리자 + 저장소", "영향도 확인·승인 후에만 시민 판정 반영"],
            ],
            [31, 52, 91],
        ),
    ])
    story.append(PageBreak())
    expected = [
        ["입력", "만 28세 / 1인 / 서울 마포구 / 연 4,200만원 / 월 실수령 300만원 / 자산 4,000만원 / 기존부채 월 30만원 / 무주택 / 중소기업 재직 / 선호 없음"],
        ["주거비", "최대 상한 86만원, 권장액 73만원, 지불능력 밴드 safe"],
        ["시나리오", "4개 결과 표시. 최상위 적합도 40점, 월 환산 143.5만원, 상한 초과로 unaffordable"],
        ["정책", "적격 4건 / 조건부 1건 / 부적격 3건"],
        ["위험", "1점 / low"],
        ["데이터", "계보 84건과 등급 C. 확인되지 않은 정책 시드·일부 지역필드·모델 상수를 강등 사유로 명시"],
    ]
    story += section_block("5", "MVP 검증 방법*", [
        callout("필수 검증 경로는 익명 시민 화면 하나입니다. 아래 샘플은 현재 커밋의 API 결과와 자동 테스트로 고정되어 있습니다."),
        Spacer(1, 3 * mm),
        grid_table(["구분", "샘플 입력 및 예상 결과"], expected, [29, 145]),
        Spacer(1, 3 * mm),
        bullet("<b>절차 A - 핵심 진단:</b> URL 접속 → '예시 프로필 채우기' → 희망지역이 서울 마포구인지 확인 → '주거비 진단 시작' → 위 표의 결과와 화면 수치를 대조합니다."),
        bullet("<b>절차 B - 설명 가능성:</b> 정책 카드와 데이터 등급을 펼쳐 적격/부적격 사유, 데이터 출처, 검증상태가 표시되는지 확인합니다."),
        bullet("<b>절차 C - AI 상담:</b> '전세랑 월세 중 뭐가 나아?' 버튼을 누릅니다. 답변이 진단 결과의 시나리오와 상한을 설명하며, 모드 칩이 현재 제공자 또는 템플릿 상태를 표시하는지 확인합니다."),
        bullet("<b>절차 D - 실패 안전:</b> 새로고침 후에도 핵심 진단이 동작해야 합니다. LLM이 오프라인이어도 F1-F5는 동일하게 작동합니다."),
        bullet("<b>계정:</b> 시민 핵심 검증은 계정 불필요. 직원·관리자 기능은 운영자 자격증명이 별도 제공된 경우에만 선택 검증합니다."),
        bullet("<b>브라우저:</b> 최신 Chrome·Edge·Safari 권장. 모바일 390px과 데스크톱 1440px을 검증했습니다. JavaScript가 필요합니다."),
        bullet("<b>제한사항:</b> 활성 정책 중 승인 전 시드 규칙과 실거래가로 도출할 수 없는 일부 필드는 화면에서 등급 C로 정직하게 표시됩니다. 실제 계약·대출 심사 전에는 소관 기관 원문을 재확인해야 합니다."),
        bullet("<b>가용성:</b> 제출 URL은 2026-09-07 11:00 KST부터 2026-09-11 23:59 KST까지 외부에서 접근 가능하도록 단일 인스턴스와 헬스체크로 운영합니다."),
    ])
    story += [para("검증 근거: python -m pytest backend/tests -q 실행 결과 2,276 passed (2026-09-01). 생성 계약·프론트 로컬 엔진·백엔드 엔진의 동등성도 같은 테스트 스위트에 포함됩니다.", "small")]
    story += evidence_appendix("부록 A. 검증 기준 화면", [
        (evidence_dir / "home_compass_dashboard.png", "[그림 2] 샘플 진단 결과 - 문서의 예상값과 화면이 같은지 대조하는 기준"),
        (evidence_dir / "home_compass_chat.png", "[그림 3] AI 상담 - 엔진 근거를 설명하고 현재 제공자/템플릿 모드를 표시"),
    ])
    return story


def build_pdf(path: Path, label: str, story: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = CompetitionDoc(path, label)
    doc.build(story)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build official-form-based competition PDFs")
    parser.add_argument("--profile", type=Path, help="submission profile JSON")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--strict", action="store_true", help="fail on operator placeholders")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    validate_profile(profile, args.strict)
    output_dir = args.output_dir.resolve()
    planning = output_dir / "2026_금융_AI_Challenge_기획서_Home_Compass.pdf"
    feature = output_dir / "2026_금융_AI_Challenge_기능명세서_Home_Compass.pdf"
    build_pdf(planning, "공모전 기획서", planning_story(profile, args.evidence_dir))
    build_pdf(feature, "기능 명세서", feature_story(profile, args.evidence_dir))
    print(planning)
    print(feature)
    if "__운영자_" in profile["member_names"]:
        print("WARNING: participant name is still operator-owned and must be filled before submission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
