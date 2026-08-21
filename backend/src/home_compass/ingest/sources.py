"""수집 대장 — 현행 `policies.json` 전수에 대응하는 원문의 소재와 이용조건.

사람이 읽는 판은 `docs/engineering/collection/SOURCES.md` 다. **이 파일이 정본**이고
그쪽이 서술이다. 둘이 갈라지지 않도록 코드포인트 수·이용조건·적재 여부는 여기서만
정하고, `backend/tests/ingest/test_manifest.py` 가 실제 파일과 대조한다.

세 가지를 이 파일에 함께 둔 이유 —
  1. **[출처 미특정] 도 한 행이다.** 못 찾은 것을 목록에서 빼면 현행 정책 전부 중 몇 건을
     다루는지가 사라진다. 비슷한 다른 상품으로 대체하지 않는다
  2. **적재 여부는 이용조건에서 파생**된다 (`loadable`). 사람이 켜고 끄는 스위치면
     이용조건과 조용히 갈라진다
  3. **코드포인트 수는 실측치**다. LLM 컨텍스트에 한 번에 들어가는지를 판단하는 재료이며
     (SPEC 잔여 실사 C — 공고문 원문 크기 상한), 지어낸 값이면 그 판단이 통째로 틀린다

★ 원문의 정본은 `data/policy_sources/*.txt` 의 텍스트다 (SPEC 4.1). 원본 PDF·HTML 을
  다시 파싱하는 경로를 만들지 않는다 — 파서 버전이 바뀌면 span 오프셋이 어긋난다.

★★ **확보 · 보관 · 적재는 세 개의 다른 칸이다.**

  | | 뜻 | 가리는 칸 |
  |---|---|---|
  | 확보 | 원문을 열어 **크기를 실측**했다 | `codepoints is not None` (`secured`) |
  | 보관 | 작업트리에 **텍스트를 둔다** | `text_file is not None` |
  | 적재 | 저장소의 `PolicySource` 로 넣는다 | `loadable` |

  이용조건이 확인되지 않은 원문은 **보관하지 않는다.** git 에 커밋하는 것도 저장·배포이므로
  「확인하지 않은 채 저장·배포하지 않는다」(SPEC 잔여 실사)가 저장소 적재와 똑같이 걸린다.
  그런 행은 URL 과 크기만 남는다 — 크기는 원문이 아니라 **관측 사실**이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

#: 수집 실행 시각(전 건 공통). 벽시계가 아니라 **기록된 취득 시각**을 `fetched_at` 으로 쓴다 —
#: 적재를 다시 돌렸다고 자료가 신선해지지 않는다.
COLLECTION_RUN_AT = datetime(2026, 8, 14, 0, 52, 0, tzinfo=KST)

#: 조회일. 공고문은 갱신되므로 대장의 모든 URL 은 이 날짜 기준이다.
RETRIEVED_ON = "2026-08-14"

#: 계약 결정 #5 의 `system:seed` 와 같은 자리. 무엇이 저장소를 바꿨는지가 감사로그에 드러난다.
INGEST_ACTOR = "system:ingest"
INGEST_ACTION = "policy_source.ingest"

_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_TEXT_DIR = _ROOT / "data" / "policy_sources"

#: 부록 A 와 같은 이유로 경로도 환경변수로 갈아끼울 수 있게 둔다.
TEXT_DIR_ENV = "HOME_COMPASS_POLICY_SOURCES_DIR"

POLICIES_JSON = Path(__file__).resolve().parents[1] / "data" / "policies.json"


def text_dir() -> Path:
    override = os.environ.get(TEXT_DIR_ENV)
    return Path(override) if override else _DEFAULT_TEXT_DIR


# --------------------------------------------------------------------------
# 어휘. 대장에 적을 수 있는 말을 먼저 고정한다.
# --------------------------------------------------------------------------

#: 무엇을 받았는가. **상품 소개와 공고문은 다르다** — 어느 쪽인지 숨기지 않는다.
DOC_KINDS = (
    "notice",  # 공고문. 공고번호가 붙은 행정 공고
    "product_page",  # 기관의 상품 안내 페이지
    "service_guide",  # 정부 복지서비스 안내(중앙)
)

#: 이용조건. **"공공누리 마크가 있다"가 아니라 "이용조건을 특정했다"** 가 확인의 뜻이다.
#:
#: ★ **순서가 있다 — 유형 확인이 협의 판정보다 먼저다.** 기관이 사전 협의를 요구하는 대상은
#: 「공공누리가 **부착되지 않은** 자료」이므로, 유형을 모르는 채로는 `CONSULTATION` 을
#: 판정할 수 없다. 앞 과업이 이 순서를 뒤집어 서울시 2건을 협의 필요로 단정했고,
#: 실제로는 제4유형이 부착돼 있었다 (`docs/engineering/collection/excerpts/공공누리-유형확인.md`).
LICENCE_FREE_USE = "free_use"  # 기관 저작권정책이 자유이용을 명시 (공공누리를 쓰지 않는 기관)
LICENCE_KOGL_TYPED = "kogl_typed"  # 공공누리 유형이 **부착**돼 있고 그 유형을 특정했다
LICENCE_CONSULTATION = "consultation_required"  # **미부착**이고 기관 정책이 사전 협의를 요구
LICENCE_UNCONFIRMED = "unconfirmed"  # 유형·조건을 특정하지 못했다 (확인 실패)
LICENCES = (
    LICENCE_FREE_USE,
    LICENCE_KOGL_TYPED,
    LICENCE_CONSULTATION,
    LICENCE_UNCONFIRMED,
)

#: **적재가 열린 이용조건.** 계약 결정 #15 가 `kogl_typed` 를 열었다 — 제4유형의 조건 넷 중
#: 셋(상업적이용금지 · 변경금지 · AI유형)이 「해당 없음」이고 **출처표시만 남기** 때문이다.
#:
#: ⚠️ 결정 #15 가 실제로 판단한 것은 **제4유형**이다. 제4유형은 제1~3유형의 조건을 모두
#: 포함하는 최강 조건이므로 그 판단이 다른 유형으로 넘어가도 성립할 여지가 크지만,
#: **그 확장은 우리가 한 판단이 아니다.** 다른 유형이 붙은 문서가 대장에 들어오면
#: 이 게이트를 다시 확인한다.
LICENCES_CLEARED = (LICENCE_FREE_USE, LICENCE_KOGL_TYPED)

#: 출처표시 문장의 **【이용근거】** — 「우리가 이 저작물을 무슨 근거로 쓰는가」다.
#: 두 갈래는 **지켜야 할 조건이 다르므로** 문자열에서 구분돼야 한다 (계약 결정 #15).
#: 형식이 7건 공통이라고 조건까지 같아지면, 나중에 조건별로 다르게 다뤄야 할 때
#: 계보만 보고 갈래를 나눌 수 없다.
#: ★ 문자열은 **계약 결정 #17 이 적은 그대로**다. 워커가 조문 제목을 붙여
#: 「제24조의2(공공저작물의 자유이용)」로 제안했으나 계약이 조문번호만 적었고 계약을 따른다.
LICENCE_BASIS_COPYRIGHT_ACT = "저작권법 제24조의2"
LICENCE_BASIS_KOGL_TYPE_4 = "공공누리 제4유형(출처표시+상업적이용금지+변경금지)"

#: 출처표시의 【공고번호】 자리에 들어가는 대체값. 공고문이 아닌 문서는 공고번호가 없으므로
#: **무엇을 받았는지**를 대신 적는다 — 빈 괄호로 두면 받은 것이 무엇인지가 사라진다.
DOC_KIND_LABELS = {
    "notice": "공고문",
    "product_page": "상품안내",
    "service_guide": "복지서비스 안내",
}

#: ★★ **우리가 저작물에 하는 일.** 이용조건 판정·심사 답변·협의 문안 어디에도
#: 「학습」이라고 쓰지 않는다 — 사실이 아니기 때문이다.
#:
#:   하는 것   : 원문 텍스트를 LLM 에 입력해 판정 규칙으로 **구조화 추출**한다
#:   하지 않는 것: **모델 학습·가중치 갱신이 없다.** 학습용 데이터셋을 만들지도 재판매하지도 않는다
#:
#: 그래서 공공누리 **AI유형의 적용 대상이 아니다.** AI유형 원문이 「'인공지능 학습용 데이터'로
#: 이용할 목적이 아닌 경우 함께 표시된 기존 공공누리 유형의 이용조건을 준수하여야 합니다」라고
#: 정하므로, 우리는 **기존 유형(제1~4유형)의 조건으로 판정받는다**
#: (`docs/engineering/diligence/excerpts/R6-공공누리-AI유형.md`).
PROCESSING_DESCRIPTION = (
    "원문 텍스트를 LLM 에 입력해 구조화 추출. 모델 학습·가중치 갱신 없음."
)


@dataclass(frozen=True)
class CollectedSource:
    """대장 한 행. 확보하지 못한 행은 `text_file` 부터 아래가 전부 `None` 이다."""

    policy_id: str
    policy_name: str
    authority: str | None
    #: **인용되는 저작물명.** 그 표면이 그 문서에 붙인 제목을 그대로 적는다.
    doc_title: str | None
    #: 공고번호. **원문 첫 줄의 표기 그대로** 옮긴다 — ⑧ 의 번호는 붙임표가 아니라
    #: EN DASH(U+2013) 인데, 출처표시는 원문이 쓴 이름을 인용하는 것이므로 고쳐 쓰지 않는다.
    #: 공고문이 아닌 문서에는 없다 (`DOC_KIND_LABELS` 가 그 자리를 대신한다).
    notice_no: str | None
    url: str | None
    doc_format: str | None
    doc_kind: str | None
    #: **작업트리에 보관한 파일.** 이용조건이 확인된 것만 보관한다 — 저장소(git)에 커밋하는 것도
    #: 저장·배포이므로, 협의가 필요하거나 유형이 미특정인 원문은 여기 두지 않는다.
    #: 확보 여부는 이 칸이 아니라 `codepoints` 가 가린다.
    text_file: str | None
    #: 실측 코드포인트 수. **확보한 8건 전부에 값이 있다** — 보관하지 않은 것도 크기는 남긴다.
    codepoints: int | None
    licence: str | None
    #: 대장 표기용. 마크다운 강조(`**`)가 섞여 있으므로 **화면이 그대로 인용할 수 없다.**
    kogl_type: str | None
    #: 출처표시 문장에 실제로 들어가는 【이용근거】. 인용되는 문자열은 여기에만 둔다 —
    #: `kogl_type` 에서 문자열을 깎아 만들면 대장의 표기를 바꿀 때마다 출처표시가 함께 움직인다.
    licence_basis: str | None
    note: str

    @property
    def identified(self) -> bool:
        """출처를 특정했는가. 특정 못 한 것을 목록에서 빼지 않고 이 값으로 구분한다."""
        return self.url is not None

    @property
    def secured(self) -> bool:
        """원문을 손에 넣고 크기를 실측했는가. **보관 여부와 다르다.**"""
        return self.codepoints is not None

    @property
    def source_id(self) -> str:
        """`PolicySource.id`. 정책 하나에 원문 하나이므로 정책 id 에서 유도한다."""
        return f"src-{self.policy_id}"

    @property
    def text_path(self) -> Path | None:
        return None if self.text_file is None else text_dir() / self.text_file

    @property
    def attribution(self) -> str | None:
        """**출처표시 문구** (계약 결정 #15). 화면이 그대로 인용하는 문장이다.

            {기관} 「{저작물명}」 ({공고번호} 또는 문서종류) · {이용근거}

        결정 #15 가 요구한 네 요소는 **두 칸에 나뉘어** 산다 — 기관·공고번호·이용근거는
        여기, **URL 은 `PolicySource.source_ref`** 다. 한 필드에 말아 넣지 않는 이유는
        `source_ref` 가 이름 그대로 참조여야 화면이 URL 만 뽑아낼 수 있기 때문이다
        (코디네이터 결정 2026-08-14). 둘은 같은 `PolicySource` 에 함께 실려 다닌다.

        ★ 한 요소라도 없으면 **`None` 을 돌려준다.** 빈칸을 채워 문장을 완성하면 그 순간
          출처표시가 「적혀 있으나 틀린 것」이 된다. 적재 경로가 `None` 을 거부한다.
        """
        if self.authority is None or self.doc_title is None or self.licence_basis is None:
            return None
        qualifier = self.notice_no or DOC_KIND_LABELS.get(self.doc_kind or "")
        if qualifier is None:
            return None
        return f"{self.authority} 「{self.doc_title}」 ({qualifier}) · {self.licence_basis}"

    @property
    def loadable(self) -> bool:
        """적재 게이트. **이용조건에서 파생**되며 따로 켜고 끄지 않는다.

        SPEC 잔여 실사 — 「확인하지 않은 채 저장·배포하지 않는다」.

        ★ **출처표시는 여기서 보지 않는다.** 출처표시가 없는 행을 조용히 걸러내면
          「이용조건 때문에 안 넣었다」와 「출처표시가 없어서 안 넣었다」가 구분되지 않고,
          결정 #15 가 요구한 **거부**가 필터로 바뀐다. 그 검사는 적재할 때 예외로 낸다
          (`loader.load_policy_sources`).
        """
        return self.licence in LICENCES_CLEARED and self.text_file is not None

    def read_text(self) -> str:
        """저장된 추출 텍스트. **정규화하지 않는다** — 정규화는 저장소가 저장 시 한 번만 한다.

        ★ `read_bytes().decode()` 이지 `read_text()` 가 아니다. 후자는 개행을 보편 개행으로
        **번역**해서 `\\r\\n` 을 `\\n` 으로 접는다. 실측으로 `youth_rent_support.txt` 가
        2,691 / 2,690 으로 갈렸다. 읽는 방식이 원문의 길이를 바꾸면 span 오프셋의 기준이
        읽는 쪽에 달리게 된다 — 그 순간 SPEC 4.2.1 이 무너진다.
        """
        path = self.text_path
        if path is None:
            raise ValueError(f"원문을 확보하지 못한 행이다: {self.policy_id}")
        return path.read_bytes().decode("utf-8")


_FUND = "국토교통부 주택도시기금 (포털 운영: 주택도시보증공사)"
_FUND_LICENCE_NOTE = (
    "기관이 **공공누리를 쓰지 않는다** — 저작권정책 페이지에도 유형 마크·KOGL 링크가 0건이다. "
    "저작권법 제24조의2 를 직접 근거로 「별도의 이용허락 없이 자유이용 가능」을 명시한다 "
    "(https://nhuf.molit.go.kr/FP/FP09/FP0902.jsp, 2026-08-14 원문확인). "
    "★ 이 정책에는 **「공공누리가 부착되지 않은 자료는 사전 협의」 조항이 없다** — "
    "서울시·국토교통부 본부 정책과 갈리는 지점이다. "
    "⚠️ 다만 `www.molit.go.kr` **본부** 저작권정책에는 그 협의 조항이 있다. 그 정책의 문언상 "
    "적용 범위는 「국토교통부 홈페이지」이고 우리는 `nhuf.molit.go.kr`(기금포털, 자체 정책 보유)에서 "
    "받았다. 어느 정책이 걸리는지는 **판단이므로 하지 않는다** — 사실만 남긴다."
)
#: ⑥⑧ 의 기관. **출처표시에 그대로 인용되므로 관측한 값을 쓴다.**
#: `www.seoul.go.kr` 고시·공고 상세의 「담당부서」 칸이 두 건 모두 **주택정책과**다
#: (⑥ 02-2133-7704 · ⑧ 02-2133-7277, 2026-08-14 원문확인).
#: 앞 과업의 코드는 `청년주거과` 였고 대장 문서는 `주택정책과` 였다 — 둘이 갈라져 있었고
#: (`SOURCES.md` 9.1 #17) 관측으로 닫는다. 어느 쪽이 조직도상 맞는지가 아니라
#: **그 공고문이 스스로 밝힌 담당부서**가 출처표시의 근거다.
_SEOUL_HOUSING_DIVISION = "서울특별시 주택정책과"
_SEOUL_KOGL_NOTE = (
    "**공공누리 제4유형(출처표시+상업적 이용금지+변경금지) 부착.** 표면은 서울주거포털이 아니라 "
    "`www.seoul.go.kr` **고시·공고 상세**다 — 게시글 본문 바로 아래에 `lic_4.jpg` 마크 이미지 · "
    "`rel=\"license\"` · https://www.kogl.or.kr/info/licenseType4.do 링크가 부착돼 있다. "
    "전역 상투구가 아니라는 대조 관측: 같은 사이트 **보도자료 상세는 마크 0건**이고 고시·공고 상세만 붙는다. "
    "서울시 정책의 사전 협의 조항은 「공공누리가 **부착되지 않은** 자료」에 걸리므로 이 건은 대상이 아니다 "
    "(https://www.seoul.go.kr/helper/copyright.do). "
    "★ 앞 과업은 서울주거포털 게시글만 보고 [협의 필요]로 단정했다 — **정정한다.** "
    "실사 원문: `docs/engineering/collection/excerpts/공공누리-유형확인.md`."
)
_FUND_KIND_NOTE = (
    "대출조건의 근거 규정은 「주택도시기금 운용 및 관리규정」(국토교통부훈령 제1830호) 제4조가 "
    "**비공개 시행세칙**에 위임하고 있어(원문확인) 공개된 공고문이 없다. "
    "따라서 이 행은 공고문이 아니라 **기관 상품 안내 페이지**다."
)

#: 순서는 `policies.json` 과 같다. 테스트가 그것을 고정한다.
SOURCES: tuple[CollectedSource, ...] = (
    CollectedSource(
        policy_id="buttress_youth",
        policy_name="청년전용 버팀목전세자금대출",
        authority=_FUND,
        doc_title="청년전용 버팀목전세자금 > 대출안내",
        notice_no=None,  # 공고문이 아니라 상품안내 페이지다
        url="https://nhuf.molit.go.kr/FP/FP05/FP0502/FP05020301.jsp",
        doc_format="html",
        doc_kind="product_page",
        text_file="buttress_youth.txt",
        codepoints=7763,
        licence=LICENCE_FREE_USE,
        kogl_type="마크 없음 (저작권법 제24조의2 자유이용 명시)",
        licence_basis=LICENCE_BASIS_COPYRIGHT_ACT,
        note=_FUND_KIND_NOTE,
    ),
    CollectedSource(
        policy_id="youth_monthly_loan",
        policy_name="청년전용 보증부월세대출",
        authority=_FUND,
        doc_title="청년전용 보증부월세대출 > 대출안내",
        notice_no=None,
        url="https://nhuf.molit.go.kr/FP/FP05/FP0502/FP05020701.jsp",
        doc_format="html",
        doc_kind="product_page",
        text_file="youth_monthly_loan.txt",
        codepoints=5344,
        licence=LICENCE_FREE_USE,
        kogl_type="마크 없음 (저작권법 제24조의2 자유이용 명시)",
        licence_basis=LICENCE_BASIS_COPYRIGHT_ACT,
        note=_FUND_KIND_NOTE,
    ),
    CollectedSource(
        policy_id="newlywed_jeonse",
        policy_name="신혼부부 전용 전세자금대출",
        authority=_FUND,
        doc_title="신혼부부전용 전세자금 > 대출안내",
        notice_no=None,
        url="https://nhuf.molit.go.kr/FP/FP05/FP0502/FP05020401.jsp",
        doc_format="html",
        doc_kind="product_page",
        text_file="newlywed_jeonse.txt",
        codepoints=7487,
        licence=LICENCE_FREE_USE,
        kogl_type="마크 없음 (저작권법 제24조의2 자유이용 명시)",
        licence_basis=LICENCE_BASIS_COPYRIGHT_ACT,
        note=_FUND_KIND_NOTE,
    ),
    CollectedSource(
        policy_id="youth_rent_support",
        policy_name="청년월세 한시 특별지원",
        authority="국토교통부 청년주거정책과 (복지로 게재)",
        doc_title="복지서비스 상세(중앙) — 청년월세 지원사업",
        notice_no=None,  # 전국 단위 단일 공고문이 없다 (5.2)
        url=(
            "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/"
            "moveTWAT52011M.do?wlfareInfoId=WLF00004661"
        ),
        doc_format="html",
        doc_kind="service_guide",
        text_file=None,  # 확인 실패 — 크기만 남기고 원문은 보관하지 않는다
        codepoints=2691,
        licence=LICENCE_UNCONFIRMED,
        kogl_type="유형번호 없는 OPEN 마크만 부착 (푸터 이미지 `ft_mark_01.png`, 링크 없음)",
        # 유형을 특정하지 못했으므로 **인용할 이용근거가 없다.** 「공공누리」라고만 적으면
        # 지키지도 못할 조건을 지킨 척하는 문장이 된다 — 무엇을 지켜야 하는지 모르기 때문이다.
        licence_basis=None,
        note=(
            "**공고문이 아니다.** 이 사업은 국토교통부가 설계하고 **지자체가 각자 시행 공고를 낸다** — "
            "전국 단위 단일 공고문이 존재하지 않는다(고양시·동대문구 등 지자체 공고가 별개로 검색된다). "
            "이용조건은 **확인 실패**다 — 「기관이 협의를 요구한다」를 확인한 것이 아니라 "
            "**유형을 정하는 문서를 찾지 못했다.** 2026-08-14 에 본 표면: 상세 페이지 전체 HTML"
            "(`lic_*` 0건 · KOGL 링크 0건) · 푸터 마크 `ft_mark_01.png`(**유형번호 없음 · 링크 없음**) · "
            "푸터 링크 전체(**저작권정책 링크가 아예 없다**) · 사이트맵(저작권 항목 없음) · "
            "추정 URL 3종(빈 셸) · 운영기관 `www.ssis.or.kr`(역시 유형번호 없는 OPEN 마크). "
            "→ **복지로에는 저작권정책 페이지 자체가 없다.** 시도하지 않은 경로: 정보공개청구 · 고객센터 문의. "
            "★ 기본 렌더는 「지원대상」 탭이며 저장된 텍스트는 그 탭까지다 "
            "(나머지 탭: 서비스 내용 · 신청방법 · 추가정보)."
        ),
    ),
    CollectedSource(
        policy_id="seoul_youth_rent",
        policy_name="서울시 청년월세지원",
        authority=_SEOUL_HOUSING_DIVISION,
        doc_title="2026년 서울시 청년월세지원 모집 공고",
        notice_no="서울특별시 공고 제2026-1440호",
        url="https://www.seoul.go.kr/news/news_notice.do?bbsNo=277&nttNo=457234",
        doc_format="pdf",
        doc_kind="notice",
        text_file="seoul_youth_rent.txt",  # 계약 결정 #15 로 적재가 열렸다
        codepoints=12248,
        licence=LICENCE_KOGL_TYPED,
        kogl_type="공공누리 **제4유형** (출처표시+상업적 이용금지+변경금지)",
        licence_basis=LICENCE_BASIS_KOGL_TYPE_4,
        note=(
            "**실제 공고문이다.** 13면. 첨부 「1. '26년 서울시 청년월세지원 모집 공고.pdf」 "
            "(413,817바이트, sha256 80de4494292b3d75…). "
            "★ **동일성 검증:** `www.seoul.go.kr` 첨부를 다시 받아 대조했고 "
            "**크기·sha256 이 바이트 단위로 일치**한다 — 앞 과업이 서울주거포털에서 받은 것과 같은 파일이며, "
            "제4유형 마크가 붙은 그 게시물의 첨부다. "
            "앞 과업 URL(`housing.seoul.go.kr/site/main/board/notice/12667`)도 같은 공고를 가리키지만, "
            "**유형이 표시되는 표면은 위 `seoul.go.kr` 고시·공고 상세**이므로 URL 을 그쪽으로 바꿨다. "
            + _SEOUL_KOGL_NOTE
        ),
    ),
    CollectedSource(
        policy_id="seoul_deposit_interest",
        policy_name="서울시 청년 임차보증금 이자지원",
        authority=_SEOUL_HOUSING_DIVISION,
        doc_title="청년 임차보증금 이자지원사업 변경계획 공고(2026.6.5.개정시행)",
        # ★ 붙임표가 아니라 EN DASH(U+2013) 다. 원문 첫 줄의 표기 그대로 옮긴 것이며
        #   출처표시는 원문이 쓴 이름을 인용하는 것이므로 ASCII 로 고쳐 쓰지 않는다.
        notice_no="서울특별시공고 제2026–1552호",
        url="https://www.seoul.go.kr/news/news_notice.do?bbsNo=277&nttNo=458161",
        doc_format="pdf",
        doc_kind="notice",
        text_file="seoul_deposit_interest.txt",  # 계약 결정 #15 로 적재가 열렸다
        codepoints=8093,
        licence=LICENCE_KOGL_TYPED,
        kogl_type="공공누리 **제4유형** (출처표시+상업적 이용금지+변경금지)",
        licence_basis=LICENCE_BASIS_KOGL_TYPE_4,
        note=(
            "**실제 공고문이다.** 11면. 첨부 「청년 임차보증금 이자지원사업 공고문('26.6.5.개정시행).pdf」 "
            "(326,314바이트, sha256 4b642332e921a528…). "
            "★ **동일성 검증:** `www.seoul.go.kr` 첨부를 다시 받아 대조했고 "
            "**크기·sha256 이 바이트 단위로 일치**한다. "
            "앞 과업 URL(`housing.seoul.go.kr/site/main/content/sh01_040901`)은 안내 페이지였고, "
            "**유형이 표시되는 표면은 위 `seoul.go.kr` 고시·공고 상세**이므로 URL 을 그쪽으로 바꿨다. "
            "★ 이 공고가 연소득 기준을 4천만원 → **5천만원**으로 올렸다 — `policies.json` 의 "
            "`annualIncomeMaxKRW: 47000000` 과 다르다. 판단은 추출 단계의 몫이므로 여기서는 사실만 적는다. "
            + _SEOUL_KOGL_NOTE
        ),
    ),
    CollectedSource(
        policy_id="housing_dream_savings",
        policy_name="청년 주택드림 청약통장",
        authority=_FUND,
        doc_title="청년 주택드림 청약통장 상품 > 상품안내",
        notice_no=None,
        url="https://nhuf.molit.go.kr/FP/FP07/FP0701/FP07010301.jsp",
        doc_format="html",
        doc_kind="product_page",
        text_file="housing_dream_savings.txt",
        codepoints=4791,
        licence=LICENCE_FREE_USE,
        kogl_type="마크 없음 (저작권법 제24조의2 자유이용 명시)",
        licence_basis=LICENCE_BASIS_COPYRIGHT_ACT,
        note=_FUND_KIND_NOTE,
    ),
    CollectedSource(
        policy_id="hug_deposit_guarantee",
        policy_name="전세보증금반환보증",
        authority="주택도시보증공사(HUG)",
        doc_title="전세보증금반환보증 > 상품개요",
        notice_no=None,
        url="https://www.khug.or.kr/hug/web/ig/dr/igdr000001.jsp",
        doc_format="html",
        doc_kind="product_page",
        text_file="hug_deposit_guarantee.txt",
        codepoints=8341,
        licence=LICENCE_FREE_USE,
        kogl_type="마크 없음 (저작권법 제24조의2 자유이용 명시)",
        licence_basis=LICENCE_BASIS_COPYRIGHT_ACT,
        note=(
            "**공고문이 아니라 상품 안내 페이지다.** 약관·보증료율표는 별도 문서이며 수집하지 않았다. "
            "이용조건: HUG 저작권 정책이 「저작권법 제24조의2에 따라 별도의 이용허락 없이 자유이용 가능」을 "
            "명시 (https://www.khug.or.kr/hug/web/cs/hg/cshg000023.jsp)."
        ),
    ),
)

#: 원문을 **확보**한 건수(크기를 실측한 건수). 보관·적재 건수와 다르다.
SECURED_COUNT = len([s for s in SOURCES if s.secured])

#: 작업트리에 원문을 **보관**한 건수. 이용조건이 확인된 것만 보관한다.
RETAINED_COUNT = len([s for s in SOURCES if s.text_file is not None])


def loadable_sources() -> tuple[CollectedSource, ...]:
    return tuple(s for s in SOURCES if s.loadable)


def collection_report() -> dict[str, int]:
    """건너뛴 것을 **세어서 내놓는다.** 조용히 빠지면 [적재 0건]과 [전부 적재]가 구분되지 않는다."""
    secured = [s for s in SOURCES if s.secured]
    loaded = [s for s in secured if s.loadable]
    return {
        "policies": len(SOURCES),
        "secured": len(secured),
        "unidentified": len([s for s in SOURCES if not s.identified]),
        "retained": len([s for s in SOURCES if s.text_file is not None]),
        "loaded": len(loaded),
        "blocked_by_licence": len(secured) - len(loaded),
        "codepoints_total": sum(s.codepoints or 0 for s in secured),
        "codepoints_max": max((s.codepoints or 0 for s in secured), default=0),
        "codepoints_min": min((s.codepoints or 0 for s in secured), default=0),
    }
