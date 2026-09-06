from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "competition" / "submission_pdf_content.py"
DEFAULT_OUTPUT = ROOT / "output" / "pdf"
DEFAULT_EVIDENCE = ROOT / "output" / "evidence"

spec = importlib.util.spec_from_file_location("submission_pdf_source", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot import {SOURCE}")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


INK = colors.HexColor("#17212B")
INK_2 = colors.HexColor("#34424E")
MUTED = colors.HexColor("#6E757C")
NAVY = colors.HexColor("#243A4A")
ACCENT = colors.HexColor("#9A6829")
LINE = colors.HexColor("#D7D5CF")
PAPER = colors.HexColor("#F8F7F3")
SOFT = colors.HexColor("#F1F3F4")
WHITE = colors.white
CRITICAL = colors.HexColor("#963737")


def humanize_markup(text: str) -> str:
    replacements = {
        "<b>Home_Compass</b> - 청년": "<b>Home_Compass</b>. 청년",
        "핵심 제안: 더 많은 금융상품을 나열하지 않고, 사용자가 지금 감당할 수 있는 주거비와 실행 가능한 다음 행동을 숫자와 근거로 먼저 좁힙니다.":
            "제안 범위: 사용자의 소득, 자산, 부채를 기준으로 감당 가능한 주거비와 계약 전 확인할 행동을 수치와 근거로 정리합니다.",
        "<b>문제 1 - 비교 기준의 파편화:</b>": "<b>문제 1: 비교 기준의 파편화</b>",
        "<b>문제 2 - 정책 정보의 잦은 변경:</b>": "<b>문제 2: 정책 정보의 잦은 변경</b>",
        "<b>문제 3 - 금융 AI의 신뢰 경계:</b>": "<b>문제 3: 금융 AI의 신뢰 경계</b>",
        "<b>왜 청년 임차 가구인가 - 데이터 근거:</b>": "<b>청년 임차 가구를 고른 근거</b>",
        "<b>제안 배경:</b> 청년에게 필요한 첫 질문은 '어떤 상품이 인기인가'가 아니라 '내가 지금 얼마짜리 집에 살아도 되는가'입니다. 이 질문을 먼저 풀어야 이후의 대출·보증·지원정책 선택이 과도한 차입을 유도하지 않습니다.":
            "<b>제안 배경</b> 청년의 첫 주거 계약에서는 감당 가능한 집의 범위를 먼저 계산해야 합니다. 이 기준이 대출, 보증, 지원정책 선택의 출발점입니다.",
        "<b>추천보다 판정:</b>": "<b>주거비 판정</b>",
        "<b>생성형 AI 역할 A - 대화형 설명:</b>": "<b>대화형 설명:</b>",
        "<b>생성형 AI 역할 B - 정책 규칙 추출:</b>": "<b>정책 규칙 추출:</b>",
        "<b>금융에서 LLM이 계산하지 않아야 하는 이유:</b>": "<b>금액과 자격을 엔진이 계산하는 이유:</b>",
        "따라서 AI를 덜 쓰는 것이 아니라 AI는 해석에 집중시키고 금전·자격 결정 권한은 재현 가능한 엔진과 사람에게 분리합니다.":
            "AI는 해석에 집중하고, 금전 및 자격 결정은 재현 가능한 엔진과 승인 담당자가 맡습니다.",
        "금융 AI 신뢰 설계 - LLM 초안·사람 승인·엔진 집행": "금융 AI 신뢰 설계: 초안 검증과 승인",
        "한 문장 원칙: LLM이 규칙 초안을 쓰고, 사람이 승인하고, 엔진이 집행합니다. 승인되지 않은 규칙은 판정에 반영되지 않습니다.":
            "운영 원칙: LLM이 만든 규칙 초안은 담당자 승인 이후 판정 엔진에 반영됩니다. 승인 전 초안은 판정에 사용할 수 없습니다.",
        "<b>왜 이것이 금융 AI의 핵심인가:</b>": "<b>금융 AI의 통제 지점</b>",
        "서비스는 금융상품 승인·판매·투자자문이 아니라 근거 있는 사전 의사결정을 돕습니다.":
            "서비스의 범위는 근거 있는 사전 의사결정 지원입니다. 금융상품 승인, 판매, 투자자문은 제공하지 않습니다.",
        "완료·관리자 계정 제공": "완료 (관리자 계정 제공)",
        "완료·관리자 계정 미제공": "완료 (관리자 계정 미제공)",
        "즉시 효력 · LLM 호출 없음": "판정에 즉시 반영되며 LLM은 호출하지 않음",
        "엔진 반환값을 근거로 설명 · 실패 시 폴백": "엔진 반환값을 설명하며 실패하면 템플릿 사용",
        "초안만 생성 · span/스키마 실패 시 차단": "초안만 생성하며 span 또는 스키마 실패 시 차단",
        "<b>절차 A - 핵심 진단:</b> URL 접속 → '예시 프로필 채우기' → 희망지역이 서울 마포구인지 확인 → '주거비 진단 시작' → 위 표의 결과와 화면 수치를 대조합니다.":
            "<b>절차 A: 핵심 진단</b> URL에 접속합니다. '예시 프로필 채우기'를 선택하고 희망지역이 서울 마포구인지 확인합니다. 이어서 '주거비 진단 시작'을 실행해 위 표와 화면 수치를 대조합니다.",
        "<b>절차 B - 설명 가능성:</b>": "<b>절차 B: 설명 가능성</b>",
        "<b>절차 C - AI 상담:</b>": "<b>절차 C: AI 상담</b>",
        "<b>절차 D - 실패 안전:</b>": "<b>절차 D: 실패 안전</b>",
        "<b>절차 E - 상담원:</b> 상담원 계정으로 로그인 → 같은 샘플 진단 실행 → 지원 제도별 신청 조건·시세 확인 시점과 출력 기능을 확인합니다.":
            "<b>절차 E: 상담원</b> 상담원 계정으로 로그인하고 같은 샘플 진단을 실행합니다. 지원 제도별 신청 조건, 시세 확인 시점, 출력 기능을 확인합니다.",
        "<b>절차 F - 정책 운영:</b> 관리자 계정으로 /admin/ 접속 → 대기 초안의 원문 span과 영향도 → 상태·감사이력을 확인합니다.":
            "<b>절차 F: 정책 운영</b> 관리자 계정으로 /admin/에 접속합니다. 대기 초안의 원문 span과 영향도를 확인한 다음 상태와 감사이력을 점검합니다.",
        "[그림 1] 접속 직후 -": "[그림 1] 접속 직후:",
        "[그림 1] 접속 직후 화면 -": "[그림 1] 접속 직후 화면:",
        "[그림 2] 익명 진단 결과 -": "[그림 2] 익명 진단 결과:",
        "[그림 2] 샘플 진단 결과 -": "[그림 2] 샘플 진단 결과:",
        "[그림 3] 진단 결과 질문 -": "[그림 3] 진단 결과 질문:",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace(" → ", ", 이어서 ")


def make_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "HC2-Title", parent=sample["Title"], fontName=source.FONT_BOLD,
            fontSize=20.5, leading=26, textColor=INK, alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "kicker": ParagraphStyle(
            "HC2-Kicker", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=8.4, leading=11, textColor=ACCENT, spaceAfter=0,
        ),
        "section_num": ParagraphStyle(
            "HC2-Section-Number", parent=sample["Heading2"], fontName=source.FONT_BOLD,
            fontSize=10.6, leading=14, textColor=ACCENT, spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "HC2-Section", parent=sample["Heading2"], fontName=source.FONT_BOLD,
            fontSize=11.3, leading=15, textColor=INK, spaceAfter=0,
        ),
        "body": ParagraphStyle(
            "HC2-Body", parent=sample["BodyText"], fontName=source.FONT,
            fontSize=8.85, leading=13.15, textColor=INK_2, wordWrap="CJK",
            spaceAfter=4.2,
        ),
        "body_bold": ParagraphStyle(
            "HC2-Body-Bold", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=8.85, leading=13.15, textColor=INK, wordWrap="CJK",
            spaceAfter=4.2,
        ),
        "bullet": ParagraphStyle(
            "HC2-Bullet", parent=sample["BodyText"], fontName=source.FONT,
            fontSize=8.75, leading=13.05, textColor=INK_2, wordWrap="CJK",
            leftIndent=10, firstLineIndent=-7, bulletIndent=0, spaceAfter=4.2,
        ),
        "small": ParagraphStyle(
            "HC2-Small", parent=sample["BodyText"], fontName=source.FONT,
            fontSize=7.35, leading=10.6, textColor=MUTED, wordWrap="CJK",
        ),
        "cell": ParagraphStyle(
            "HC2-Cell", parent=sample["BodyText"], fontName=source.FONT,
            fontSize=7.65, leading=10.55, textColor=INK_2, wordWrap="CJK",
        ),
        "cell_head": ParagraphStyle(
            "HC2-Cell-Head", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=7.65, leading=10.55, textColor=INK, wordWrap="CJK",
            alignment=TA_CENTER,
        ),
        "cell_head_white": ParagraphStyle(
            "HC2-Cell-Head-White", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=7.65, leading=10.55, textColor=WHITE, wordWrap="CJK",
            alignment=TA_CENTER,
        ),
        "callout": ParagraphStyle(
            "HC2-Callout", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=9.05, leading=13.7, textColor=INK, wordWrap="CJK",
        ),
        "placeholder": ParagraphStyle(
            "HC2-Placeholder", parent=sample["BodyText"], fontName=source.FONT_BOLD,
            fontSize=8.5, leading=12, textColor=CRITICAL, wordWrap="CJK",
        ),
    }


ST = make_styles()


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(humanize_markup(text), ST[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(humanize_markup(text), ST["bullet"], bulletText="▪")


def section_heading(number: str, title: str) -> Table:
    return Table(
        [[para(number, "section_num"), para(humanize_markup(title), "section")]],
        colWidths=[6 * mm, 168 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.85, NAVY),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 0),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]),
    )


def section_block(number: str, title: str, items: list, note: str | None = None):
    head = section_heading(number, title)
    body = []
    if note:
        body.extend([para(note, "small"), Spacer(1, 1.6 * mm)])
    for item in items:
        body.append(para(item) if isinstance(item, str) else item)
    if not body:
        return [head, Spacer(1, 3.2 * mm)]
    if isinstance(body[0], Table) and getattr(body[0], "_nrows", 0) > 6:
        return [head, Spacer(1, 2.6 * mm), *body, Spacer(1, 3.8 * mm)]
    first = KeepTogether([head, Spacer(1, 2.6 * mm), body[0]])
    return [first, *body[1:], Spacer(1, 3.8 * mm)]


def identity_header(_attachment: str, title: str, profile: dict[str, object]):
    member_names = str(profile["member_names"])
    member_style = "placeholder" if "__운영자_" in member_names else "body"
    identity = Table(
        [
            [para("팀명", "cell_head"), para(str(profile["team_name"]), "body")],
            [para("구성원 성명", "cell_head"), para(member_names, member_style)],
        ],
        colWidths=[37 * mm, 137 * mm],
        rowHeights=[10.5 * mm, 10.5 * mm],
        style=TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 0.7, NAVY),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
            ("BACKGROUND", (0, 0), (0, -1), SOFT),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    return [
        para(title, "title"),
        Spacer(1, 3 * mm),
        HRFlowable(width="100%", thickness=2.2, color=ACCENT, spaceBefore=0, spaceAfter=5 * mm),
        identity,
        Spacer(1, 1.5 * mm),
        para("* 필수항목", "small"),
        Spacer(1, 5 * mm),
    ]


def callout(text: str):
    return Table(
        [[para(text, "callout")]],
        colWidths=[174 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PAPER),
            ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    )


def grid_table(headers: list[str], rows: list[list[str]], widths: list[float]):
    data = [[para(h, "cell_head_white") for h in headers]]
    data.extend([[para(cell, "cell") for cell in row] for row in rows])
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#FAFAF8")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
    ]
    return Table(data, colWidths=[w * mm for w in widths], repeatRows=1, style=TableStyle(table_style))


def evidence_appendix(title: str, items: list[tuple[Path, str]]):
    contents = []
    for path, caption in items:
        contents += source.screenshot(path, humanize_markup(caption), height_mm=72)
    if not contents:
        return []
    return [PageBreak(), section_heading("A", title.removeprefix("부록 A. ")), Spacer(1, 4 * mm), *contents]


class CompetitionDoc(BaseDocTemplate):
    def __init__(self, filename: Path, doc_label: str):
        super().__init__(
            str(filename), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=15 * mm,
            title=doc_label, author="Home_Compass", subject="2026 금융 AI Challenge",
            creator="Home_Compass submission builder", invariant=1,
        )
        self.doc_label = doc_label
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates(PageTemplate(id="all", frames=[frame], onPage=self._page))

    def _page(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.45)
        canvas.line(18 * mm, 11.5 * mm, 192 * mm, 11.5 * mm)
        canvas.setFont(source.FONT, 7.1)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 7.7 * mm, f"Home_Compass  {self.doc_label}")
        canvas.drawRightString(192 * mm, 7.7 * mm, str(doc.page))
        canvas.restoreState()


source.INK = INK
source.INK_2 = INK_2
source.INK_3 = MUTED
source.ACCENT = ACCENT
source.ACCENT_DEEP = ACCENT
source.ACCENT_WASH = PAPER
source.PANEL = SOFT
source.LINE = LINE
source.WHITE = WHITE
source.CRITICAL = CRITICAL
source.ST = ST
source.para = para
source.bullet = bullet
source.section_block = section_block
source.identity_header = identity_header
source.callout = callout
source.grid_table = grid_table
source.evidence_appendix = evidence_appendix
source.CompetitionDoc = CompetitionDoc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build final competition PDFs")
    parser.add_argument("--profile", type=Path, help="submission profile JSON")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--strict", action="store_true", help="fail on operator placeholders")
    args = parser.parse_args(argv)

    profile = source.load_profile(args.profile)
    source.validate_profile(profile, args.strict)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    planning = output_dir / "2026_금융_AI_Challenge_기획서_Home_Compass.pdf"
    feature = output_dir / "2026_금융_AI_Challenge_기능명세서_Home_Compass.pdf"
    source.build_pdf(planning, "공모전 기획서", source.planning_story(profile, args.evidence_dir))
    source.build_pdf(feature, "기능 명세서", source.feature_story(profile, args.evidence_dir))
    print(planning)
    print(feature)
    if "__운영자_" in str(profile["member_names"]):
        print("WARNING: participant name is still operator-owned and must be filled before submission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
