import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SKILL_DIR = process.env.PRESENTATIONS_SKILL_DIR;
const RUNTIME_PYTHON = process.env.RUNTIME_PYTHON;
if (!SKILL_DIR || !RUNTIME_PYTHON) {
  throw new Error("PRESENTATIONS_SKILL_DIR and RUNTIME_PYTHON must be set by build_ppt.py");
}

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceDir = path.resolve(scriptDir, "..", "..");
const TMP_DIR = path.join(workspaceDir, "tmp/ppt-build");
const FINAL_PPTX = process.env.FINAL_PPTX || path.join(workspaceDir, "docs/competition/기술설명서_Home_Compass.pptx");
const openApi = JSON.parse(await fs.readFile(path.join(workspaceDir, "contracts/openapi.json"), "utf8"));
const httpMethods = new Set(["get", "post", "put", "delete", "patch"]);
const endpointCount = Object.values(openApi.paths ?? {}).reduce(
  (count, pathItem) => count + Object.keys(pathItem).filter((method) => httpMethods.has(method)).length,
  0,
);

const { importRuntimeModule } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/runtime_helpers.mjs")).href,
);
const { Presentation, PresentationFile } = await importRuntimeModule("@oai/artifact-tool");
const { finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

// Match the source deck's exact 13.332999-inch width (12191695 EMU).
const W = 12191695 / 9525;
const H = 720;
const FONT = "맑은 고딕";
const C = {
  paper: "#F7F5F0",
  white: "#FFFFFF",
  ink: "#161A1D",
  ink2: "#3F464D",
  muted: "#6D747A",
  faint: "#9AA0A5",
  line: "#D7D4CC",
  line2: "#BDB9B0",
  navy: "#18324A",
  navy2: "#294A64",
  blueWash: "#E8EEF2",
  amber: "#B77913",
  amberWash: "#F4E8D0",
  green: "#356B57",
  greenWash: "#E3ECE7",
  red: "#A3483C",
  redWash: "#F2E4E1",
  grayWash: "#EEECE7",
};

const presentation = Presentation.create({ slideSize: { width: W, height: H } });

function text(slide, name, value, x, y, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position: { left: x, top: y, width, height },
    fill: options.fill ?? "none",
    line: options.line ?? { style: "solid", fill: "none", width: 0 },
    borderRadius: options.borderRadius,
  });
  shape.text = value;
  shape.text.style = {
    typeface: FONT,
    fontSize: options.size ?? 18,
    bold: options.bold ?? false,
    color: options.color ?? C.ink,
    alignment: options.align ?? "left",
    verticalAlignment: options.valign ?? "top",
    lineSpacing: options.lineSpacing ?? 1.08,
    autoFit: options.autoFit ?? "none",
    wrap: "square",
    insets: options.insets ?? { left: 0, right: 0, top: 0, bottom: 0 },
  };
  return shape;
}

function box(slide, name, x, y, width, height, options = {}) {
  const geometry = options.geometry ?? "rect";
  const config = {
    geometry,
    name,
    position: { left: x, top: y, width, height },
    fill: options.fill ?? C.white,
    line: options.line ?? { style: "solid", fill: C.line, width: 1 },
    shadow: "shadow-none",
  };
  if (["rect", "textbox", "roundRect"].includes(geometry)) {
    config.borderRadius = options.borderRadius ?? 0;
  }
  return slide.shapes.add(config);
}

function rule(slide, name, x, y, width, height = 0, color = C.line, weight = 1) {
  return slide.shapes.add({
    geometry: "line",
    name,
    position: { left: x, top: y, width, height },
    fill: "none",
    line: { style: "solid", fill: color, width: weight },
  });
}

function fillSlide(slide, color = C.paper) {
  slide.background.fill = color;
}

function header(slide, number, title, subtitle) {
  text(slide, `slide-${number}-number`, String(number).padStart(2, "0"), 72, 40, 42, 26, {
    size: 14, bold: true, color: C.amber,
  });
  rule(slide, `slide-${number}-head-rule`, 116, 51, 30, 0, C.amber, 2);
  text(slide, `slide-${number}-title`, title, 160, 31, 1048, 52, {
    size: 36, bold: true, color: C.ink, lineSpacing: 0.98,
  });
  if (subtitle) {
    text(slide, `slide-${number}-subtitle`, subtitle, 160, 87, 1048, 40, {
      size: 17, color: C.muted,
    });
  }
}

function footer(slide, number) {
  rule(slide, `slide-${number}-footer-rule`, 72, 676, 1136, 0, C.line, 1);
  text(slide, `slide-${number}-footer-left`, "Home_Compass   2026 금융 AI Challenge", 72, 685, 600, 18, {
    size: 11, color: C.faint,
  });
  text(slide, `slide-${number}-footer-right`, `${String(number).padStart(2, "0")} / 19`, 990, 685, 190, 18, {
    size: 11, bold: true, color: C.faint, align: "right",
  });
}

function addSlide(number, title, subtitle) {
  const slide = presentation.slides.add();
  fillSlide(slide);
  if (title) header(slide, number, title, subtitle);
  if (number > 1) footer(slide, number);
  return slide;
}

function label(slide, name, value, x, y, width, color = C.amber) {
  text(slide, name, value, x, y, width, 20, { size: 12, bold: true, color });
}

function numberedItem(slide, prefix, number, titleValue, bodyValue, x, y, width, height, options = {}) {
  text(slide, `${prefix}-num`, String(number).padStart(2, "0"), x, y, 54, 28, {
    size: 18, bold: true, color: options.numberColor ?? C.amber,
  });
  text(slide, `${prefix}-title`, titleValue, x + 62, y - 1, width - 62, 30, {
    size: options.titleSize ?? 20, bold: true, color: options.titleColor ?? C.ink,
  });
  text(slide, `${prefix}-body`, bodyValue, x + 62, y + 38, width - 62, height - 38, {
    size: options.bodySize ?? 16, color: options.bodyColor ?? C.ink2,
    lineSpacing: options.lineSpacing ?? 1.22,
  });
}

function columnTitle(slide, prefix, value, x, y, width, color = C.navy) {
  rule(slide, `${prefix}-accent`, x, y, 32, 0, color, 3);
  text(slide, `${prefix}-title`, value, x, y + 12, width, 28, { size: 17, bold: true, color });
}

function listText(lines) {
  return lines.map((line) => `• ${line}`).join("\n");
}

// 01. Cover
{
  const slide = presentation.slides.add();
  fillSlide(slide, C.navy);
  box(slide, "cover-accent", 72, 62, 5, 54, { fill: C.amber, line: { style: "solid", fill: "none", width: 0 } });
  text(slide, "cover-kicker", "2026 금융 AI Challenge\n기술설명서", 96, 58, 360, 62, {
    size: 14, bold: true, color: C.amberWash, lineSpacing: 1.18,
  });
  text(slide, "cover-title", "Home_Compass", 72, 181, 860, 82, {
    size: 58, bold: true, color: C.white, lineSpacing: 0.92,
  });
  text(slide, "cover-subtitle", "청년 주거 금융 의사결정 서비스", 74, 276, 780, 38, {
    size: 22, color: "#CFD8DF",
  });
  rule(slide, "cover-rule", 74, 348, 128, 0, C.amber, 4);
  text(slide, "cover-summary",
    "청년 임차 가구의 월 주거비 상한, 전월세 총비용, 정책 자격, 보증금 위험을\n같은 기준으로 계산하고 근거까지 보여줍니다.",
    74, 387, 780, 84, { size: 22, color: C.white, lineSpacing: 1.26 });
  text(slide, "cover-meta", "기술 구조와 검증 범위, 19쪽", 74, 638, 520, 24, {
    size: 13, color: "#A9B6C0",
  });
  text(slide, "cover-index", "01", 1128, 614, 80, 54, {
    size: 34, bold: true, color: C.amber, align: "right",
  });
}

// 02. Problem
{
  const slide = addSlide(2, "청년 임차 의사결정의 네 가지 공백", "정보는 많지만 개인별 기준선과 비교 단위가 연결되지 않습니다");
  rule(slide, "p2-v", 640, 156, 0, 424, C.line, 1);
  rule(slide, "p2-h", 72, 366, 1136, 0, C.line, 1);
  numberedItem(slide, "p2-1", 1, "월 주거비 기준선", "소득, 자산, 부채, 가구원 수를 넣어도\n감당 가능한 월 상한을 제시하는 서비스가 드뭅니다.\n사용자는 주변 사례를 기준으로 계약을 판단합니다.", 72, 172, 520, 166);
  numberedItem(slide, "p2-2", 2, "전세와 월세의 비교 단위", "월 납입액만 비교하면 대출이자와 관리비,\n보증금 기회비용, 보증료가 빠집니다.\n5년 총비용 기준의 비교가 필요합니다.", 688, 172, 520, 166);
  numberedItem(slide, "p2-3", 3, "정책 자격 확인", "제도마다 연령, 소득, 자산, 지역 요건이 다릅니다.\n사용자가 여러 공고문을 직접 대조해야 하며\n제외 사유와 추가 확인 항목도 한눈에 보기 어렵습니다.", 72, 392, 520, 166);
  numberedItem(slide, "p2-4", 4, "계약 전 보증금 점검", "전세가율과 보증 가입 가능성 같은 신호를\n계약 전에 한 점수로 확인하기 어렵습니다.\n사고가 난 뒤에야 위험을 이해하는 경우가 많습니다.", 688, 392, 520, 166);
  rule(slide, "p2-note-rule", 72, 598, 4, 42, C.amber, 4);
  text(slide, "p2-note", "참고: 이 장은 검증 가능한 통계 수치를 새로 만들지 않았습니다. 공개 제도 요건과 일반적인 계약 절차를 기준으로 문제를 정리했습니다.", 92, 598, 1116, 44, {
    size: 13, color: C.muted, lineSpacing: 1.18,
  });
}

// 03. Existing services
{
  const slide = addSlide(3, "기존 서비스가 제공하는 범위", "각 서비스는 일부 정보를 잘 제공하지만 개인 상황에 대한 종합 판정은 남아 있습니다");
  const cols = [72, 356, 640, 924];
  const heads = ["상담형 챗봇", "대출 계산기", "정책 포털", "부동산 시세 앱"];
  const strengths = ["자연어로 질문을 받을 수 있음", "원리금 계산이 정확함", "공식 제도 목록과 원문 제공", "매물과 지역 시세가 풍부함"];
  const gaps = ["수치 생성의 재현성", "감당 가능한 금액 판단", "개인별 적격 여부와 제외 사유", "재무 관점의 총비용 비교"];
  for (let i = 0; i < 4; i += 1) {
    if (i > 0) rule(slide, `p3-v-${i}`, cols[i] - 22, 168, 0, 292, C.line, 1);
    text(slide, `p3-head-${i}`, heads[i], cols[i], 170, 242, 32, { size: 20, bold: true, color: C.ink });
    label(slide, `p3-good-label-${i}`, "제공", cols[i], 226, 80, C.green);
    text(slide, `p3-good-${i}`, strengths[i], cols[i], 250, 240, 72, { size: 16, color: C.ink2, lineSpacing: 1.2 });
    label(slide, `p3-gap-label-${i}`, "남은 판단", cols[i], 338, 100, C.red);
    text(slide, `p3-gap-${i}`, gaps[i], cols[i], 362, 240, 70, { size: 17, bold: true, color: C.ink });
  }
  box(slide, "p3-answer-bg", 72, 486, 1136, 142, { fill: C.blueWash, line: { style: "solid", fill: "none", width: 0 } });
  text(slide, "p3-answer-label", "Home_Compass의 범위", 96, 506, 250, 28, { size: 15, bold: true, color: C.navy });
  text(slide, "p3-answer-main", "월 주거비 상한을 먼저 확정한 뒤 전월세 총비용, 정책 자격, 보증금 위험을 같은 입력으로 계산합니다.", 96, 543, 1040, 34, {
    size: 21, bold: true, color: C.navy,
  });
  text(slide, "p3-answer-sub", "금액과 판정은 결정론적 엔진이 만들고, LLM은 이미 계산된 결과를 설명합니다.", 96, 588, 1040, 26, {
    size: 16, color: C.navy2,
  });
}

// 04. Service overview with screenshot
{
  const slide = addSlide(4, "Home_Compass의 판정 범위", "한 번의 입력으로 재무 기준선과 실행 가능한 선택지를 함께 확인합니다");
  label(slide, "p4-label", "서비스 정의", 72, 162, 150, C.amber);
  text(slide, "p4-definition", "청년 임차 가구가 자신의 소득과 자산으로 감당 가능한 집의 범위를 먼저 계산하고, 전세와 월세 비용 및 정책 자격을 같은 근거에서 비교하는 서비스", 72, 192, 410, 116, {
    size: 22, bold: true, color: C.ink, lineSpacing: 1.24,
  });
  rule(slide, "p4-left-rule", 72, 334, 410, 0, C.line2, 1);
  text(slide, "p4-left-note", "입력에는 나이, 가구원 수, 희망 지역, 소득, 자산, 부채, 주거 조건이 포함됩니다. 시민 기능은 로그인 없이 사용할 수 있습니다.", 72, 354, 410, 92, {
    size: 16, color: C.ink2, lineSpacing: 1.22,
  });
  const imgBytes = await fs.readFile(path.join(workspaceDir, "output/evidence/home_compass_onboarding.png"));
  slide.images.add({
    blob: imgBytes,
    contentType: "image/png",
    alt: "Home_Compass 프로필 입력 화면",
    fit: "contain",
    position: { left: 530, top: 157, width: 678, height: 350 },
  });
  rule(slide, "p4-image-bottom", 530, 516, 678, 0, C.line2, 1);
  text(slide, "p4-image-caption", "실제 실행 화면: 프로필 입력과 제공 기능 안내", 530, 525, 678, 22, { size: 12, color: C.muted });
  const steps = [
    ["1", "프로필 입력", "개인 재무 조건과 희망 지역"],
    ["2", "엔진 계산", "상한, 비용, 자격, 위험"],
    ["3", "결과 확인", "판정 사유와 출처"],
    ["4", "후속 질문", "엔진 결과를 근거로 설명"],
  ];
  steps.forEach((s, i) => {
    const x = 72 + i * 284;
    text(slide, `p4-step-num-${i}`, s[0], x, 582, 30, 26, { size: 15, bold: true, color: C.amber });
    text(slide, `p4-step-head-${i}`, s[1], x + 38, 580, 230, 26, { size: 18, bold: true, color: C.ink });
    text(slide, `p4-step-copy-${i}`, s[2], x + 38, 610, 230, 36, { size: 14, color: C.muted });
    if (i < 3) rule(slide, `p4-step-rule-${i}`, x + 270, 581, 0, 62, C.line, 1);
  });
}

// 05. Design decisions
{
  const slide = addSlide(5, "판정 구조의 네 가지 설계 결정", "계산 권한과 검증 책임을 분명히 나눈 네 가지 기준입니다");
  const rows = [
    ["주거비 기준선", "가처분소득에서 생활비, 기존 부채, 안전 버퍼를 뺀 뒤 소득 비율 상한과 교차해 월 상한과 권장액을 계산합니다."],
    ["동일 단위의 비용 비교", "전세, 반전세, 월세를 5년 총비용과 현재가치로 비교합니다. 보증금 기회비용과 보증료도 비용 구성에 포함합니다."],
    ["판정 사유 보존", "모든 엔진은 결과와 함께 reasons 또는 rationale을 반환합니다. 화면, API, 상담 답변에서 같은 근거를 확인할 수 있습니다."],
    ["LLM 권한 제한", "LLM은 엔진 도구를 호출하고 반환값을 설명합니다. 금액과 자격 판정을 새로 만들지 않으며 연결 실패 시 템플릿 답변으로 전환됩니다."],
  ];
  rows.forEach((row, i) => {
    const y = 160 + i * 112;
    text(slide, `p5-num-${i}`, String(i + 1).padStart(2, "0"), 72, y + 3, 52, 28, { size: 16, bold: true, color: C.amber });
    text(slide, `p5-title-${i}`, row[0], 148, y, 290, 32, { size: 21, bold: true, color: C.ink });
    text(slide, `p5-copy-${i}`, row[1], 470, y, 738, 70, { size: 17, color: C.ink2, lineSpacing: 1.24 });
    rule(slide, `p5-row-${i}`, 72, y + 91, 1136, 0, C.line, 1);
  });
  text(slide, "p5-end", "동일 입력은 같은 판정을 반환하고, 모델 연결 여부는 핵심 계산에 영향을 주지 않습니다.", 148, 620, 1060, 28, {
    size: 18, bold: true, color: C.navy,
  });
}

// 06. Architecture
{
  const slide = addSlide(6, "시스템 아키텍처", "클라이언트, API, 판정 엔진, 저장소를 분리하고 LLM 연결은 별도 경계에 둡니다");
  const layerY = [160, 250, 340, 430];
  const layerNames = ["L1  클라이언트", "L2  API", "L3  판정 엔진", "L4  데이터"];
  const layerContent = [
    ["프로필 입력", "결과 화면", "AI 상담"],
    ["FastAPI main.py", "GET health / regions", "POST analyze / chat"],
    ["E1 지불능력", "E2 정책 자격", "E3 총비용", "E4 보증금 위험"],
    ["SQLite 저장소", "data/*.json 시드", "출처와 고지 필드"],
  ];
  layerY.forEach((y, i) => {
    box(slide, `p6-layer-bg-${i}`, 72, y, 806, 72, { fill: i % 2 === 0 ? C.white : C.grayWash, line: { style: "solid", fill: "none", width: 0 } });
    text(slide, `p6-layer-name-${i}`, layerNames[i], 92, y + 24, 170, 24, { size: 15, bold: true, color: C.navy });
    const start = 282;
    const available = 576;
    const cellW = available / layerContent[i].length;
    layerContent[i].forEach((item, j) => {
      if (j > 0) rule(slide, `p6-layer-sep-${i}-${j}`, start + j * cellW - 12, y + 17, 0, 38, C.line, 1);
      text(slide, `p6-layer-item-${i}-${j}`, item, start + j * cellW, y + 23, cellW - 20, 30, { size: 15, color: C.ink2, align: "center" });
    });
  });
  columnTitle(slide, "p6-side", "LLM 연결 경계", 920, 160, 288, C.amber);
  text(slide, "p6-side-copy", "상담 요청에서만 사용\n엔진 도구 스키마를 공통 형식으로 변환\n금액과 판정은 엔진 반환값만 사용", 920, 208, 288, 102, {
    size: 16, color: C.ink2, lineSpacing: 1.35,
  });
  rule(slide, "p6-side-divider", 920, 330, 288, 0, C.line, 1);
  label(slide, "p6-provider-label", "연결 순서", 920, 352, 120, C.navy);
  text(slide, "p6-provider-copy", "1  OpenAI function calling\n2  Anthropic tool use\n3  결정론적 템플릿", 920, 382, 288, 96, { size: 17, color: C.ink, lineSpacing: 1.38 });
  text(slide, "p6-contract", `시민 판정 경로 4종\nAPI 계약 전체는 ${endpointCount}종`, 920, 520, 288, 58, { size: 18, bold: true, color: C.navy, lineSpacing: 1.25 });
  text(slide, "p6-note", "백엔드 미기동 시에도 생성물 기반 로컬 판정으로 핵심 화면을 재현합니다.", 72, 602, 1136, 34, { size: 15, color: C.muted });
}

// 07. Engine pipeline
{
  const slide = addSlide(7, "판정 엔진의 처리 순서", "E1에서 월 주거비 상한을 확정하고 나머지 엔진이 그 값을 공통 제약으로 사용합니다");
  const xs = [72, 330, 590, 930];
  const ws = [222, 222, 304, 278];
  const headings = ["입력", "기준선 계산", "병렬 평가", "응답 구성"];
  const copies = [
    "나이와 가구 조건\n소득, 자산, 부채\n희망 지역과 주거 조건",
    "E1 지불능력\n월 상한과 권장액\n소득·부채 밴드",
    "E2 정책 자격\nE3 전월세 총비용과 NPV\nE4 보증금 위험 점수",
    "affordability\nscenarios / policies / risk\nsummary / meta / internal",
  ];
  xs.forEach((x, i) => {
    text(slide, `p7-num-${i}`, String(i + 1).padStart(2, "0"), x, 168, 54, 34, { size: 19, bold: true, color: i === 1 ? C.amber : C.navy });
    text(slide, `p7-head-${i}`, headings[i], x, 216, ws[i], 34, { size: 22, bold: true, color: C.ink });
    rule(slide, `p7-rule-${i}`, x, 266, ws[i] - 18, 0, i === 1 ? C.amber : C.line2, i === 1 ? 3 : 1);
    text(slide, `p7-copy-${i}`, copies[i], x, 292, ws[i] - 18, 136, { size: 17, color: C.ink2, lineSpacing: 1.42 });
    if (i < 3) rule(slide, `p7-sep-${i}`, x + ws[i] - 6, 168, 0, 260, C.line, 1);
  });
  box(slide, "p7-result", 72, 476, 1136, 142, { fill: C.blueWash, line: { style: "solid", fill: "none", width: 0 } });
  text(slide, "p7-result-head", "판정 근거", 96, 498, 180, 26, { size: 16, bold: true, color: C.navy });
  text(slide, "p7-result-copy", "각 응답 블록에는 rationale, reasons 또는 factors가 포함됩니다. 상담 LLM은 이 배열과 엔진 수치를 이용해 설명하며 숫자를 다시 계산하지 않습니다.", 96, 534, 1056, 55, {
    size: 19, bold: true, color: C.navy, lineSpacing: 1.22,
  });
}

function engineSlide(number, config) {
  const slide = addSlide(number, config.title, config.subtitle);
  label(slide, `p${number}-engine-label`, `판정 엔진 ${number - 7} / 4`, 72, 154, 150, config.accent ?? C.amber);
  rule(slide, `p${number}-col-a`, 330, 176, 0, 330, C.line, 1);
  rule(slide, `p${number}-col-b`, 860, 176, 0, 330, C.line, 1);
  columnTitle(slide, `p${number}-input`, "입력", 72, 188, 230, C.navy);
  text(slide, `p${number}-input-copy`, config.input, 72, 236, 226, 250, { size: 16, color: C.ink2, lineSpacing: 1.42 });
  columnTitle(slide, `p${number}-logic`, "계산 규칙", 366, 188, 458, config.accent ?? C.amber);
  config.logic.forEach((item, i) => {
    const y = 236 + i * 62;
    text(slide, `p${number}-logic-num-${i}`, String(i + 1), 366, y, 28, 30, { size: 18, bold: true, color: config.accent ?? C.amber });
    text(slide, `p${number}-logic-copy-${i}`, item, 408, y - 1, 414, 46, { size: 17, color: C.ink, lineSpacing: 1.14 });
  });
  columnTitle(slide, `p${number}-output`, "출력", 896, 188, 312, C.navy);
  text(slide, `p${number}-output-copy`, config.output, 896, 236, 312, 250, { size: 16, color: C.ink2, lineSpacing: 1.38 });
  box(slide, `p${number}-example-bg`, 72, 528, 1136, 110, { fill: config.wash ?? C.amberWash, line: { style: "solid", fill: "none", width: 0 } });
  text(slide, `p${number}-example-label`, "엔진 반환 예시", 94, 547, 160, 24, { size: 14, bold: true, color: config.accent ?? C.amber });
  text(slide, `p${number}-example`, config.example, 94, 579, 1080, 48, { size: 15, color: C.ink, lineSpacing: 1.18 });
  return slide;
}

engineSlide(8, {
  title: "E1 주거지불능력 엔진",
  subtitle: "가처분소득에서 실제 잔여 여력을 계산해 월 주거비 상한과 권장액을 구합니다",
  accent: C.amber,
  wash: C.amberWash,
  input: "월 실수령액\n연소득\n기존 부채 월 상환액\n가구원 수",
  logic: [
    "비율 상한 = 가처분소득 × 상한 비율",
    "잔여 여력 = 소득 − 생활비 − 기존 부채 − 안전 버퍼",
    "비율 상한과 잔여 여력 중 작은 값을 월 상한으로 확정",
    "월 상한에 안전 마진을 적용해 권장액 산출",
  ],
  output: "maxMonthlyHousingCostKRW\nrecommendedMonthlyHousingCostKRW\nbreakdown\nband\nrationale[]\n\n밴드: safe / caution / risk",
  example: "소득 대비 비율보다 실제 잔여 여력이 더 빠듯해 잔여 여력 기준으로 상한을 86만원으로 확정했습니다.\n소득 대비 주거비 여력이 안정적인 구간입니다.",
});

engineSlide(9, {
  title: "E2 정책 적격성 룰엔진",
  subtitle: "승인된 규칙을 조건별로 평가하고 적격 여부와 사유를 같은 순서로 반환합니다",
  accent: C.green,
  wash: C.greenWash,
  input: "나이와 연소득\n보유 자산\n무주택 여부\n희망 지역 코드\n신혼 및 재직 조건",
  logic: [
    "저장소에서 승인된\nRuleVersion만 불러옴",
    "연령, 소득, 자산, 무주택, 지역, 재직,\n혼인 요건을 순차 평가",
    "모두 충족: eligible\n추가 확인 필요: conditional",
    "명확한 미충족: ineligible",
  ],
  output: "status\nreasons[]\nmaxAmountKRW\nrateRangePct\nsource\ndisclaimer\n\n판정과 사유는 1:1로 대응",
  example: "만 19~34세 요건 충족(28세), 연소득 5,000만원 이하 충족(4,200만원).\n주택 유형, 전세가율, 선순위 채권 규모에 따라 보증 가입이 제한될 수 있습니다.",
});

engineSlide(10, {
  title: "E3 전월세 총비용 비교 엔진",
  subtitle: "월 납입액 대신 5년 총비용과 현재가치로 전세, 반전세, 월세를 비교합니다",
  accent: C.navy2,
  wash: C.blueWash,
  input: "보증금\n월세와 관리비\n대출 금액과 금리\n보유 자산\n비교 기간 5년",
  logic: [
    "월세, 관리비, 대출이자, 보증료를 월 단위로 전개",
    "보증금에 묶이는 자기자본의 기회비용을 더함",
    "5년 총비용(TCO)과 할인한 현재가치(NPV) 계산",
    "E1 상한과 비교해 적합도 점수와 verdict 산출",
  ],
  output: "monthlyEquivalentCostKRW\ntco5yKRW / npv5yKRW\ncomponents\nfitScore\nverdict\nrationale[]",
  example: "보증금에 묶이는 자기자본 5,500만원의 기회비용을 연 3.3%로 계산해 897만원을 총비용에 포함했습니다. 보증금 원금은 계약 종료 시 반환되므로 비용에서 제외합니다.",
});

engineSlide(11, {
  title: "E4 전세보증금 리스크 스캐너",
  subtitle: "계약 전에 확인할 위험 신호를 0~100점으로 합산하고 점검 순서를 제시합니다",
  accent: C.red,
  wash: C.redWash,
  input: "보증금\n전세가율\n보증금 내 대출 비중\n보증 가입 가능 여부\n지역 시장 위험도",
  logic: [
    "위험 요인 값을\n공통 범위로 정규화",
    "요인별 가중치를 적용하고 합산",
    "합산값을 0~100 점수로 변환",
    "low 0–34 / medium 35–64\nhigh 65–100",
  ],
  output: "score\nband\nfactors[].name\nfactors[].valuePct\nfactors[].impact\nfactors[].note\n\n법적 안전을 보증하지 않는 참고 지표",
  example: "서울 마포구 기준 보증금 2억 8,000만원의 위험 점수는 100점 만점에 32점(low)입니다.\n가장 큰 위험 요인은 보증금 내 대출 비중입니다.",
});

// 12. LLM scope
{
  const slide = addSlide(12, "LLM 사용 범위와 실패 처리", "모델은 엔진을 호출하고 결과를 설명합니다. 계산 권한은 판정 엔진에만 있습니다");
  const top = [
    ["01", "사용자 질문", "자연어 후속 질문"],
    ["02", "프로바이더 선택", "설정된 연결과 상태 확인"],
    ["03", "도구 호출", "E1~E4 함수 실행"],
    ["04", "엔진 반환", "숫자와 rationale 수신"],
    ["05", "답변 작성", "반환값을 고객 언어로 설명"],
  ];
  top.forEach((item, i) => {
    const x = 72 + i * 227;
    if (i > 0) rule(slide, `p12-top-sep-${i}`, x - 18, 160, 0, 128, C.line, 1);
    text(slide, `p12-top-num-${i}`, item[0], x, 164, 44, 24, { size: 14, bold: true, color: C.amber });
    text(slide, `p12-top-head-${i}`, item[1], x, 202, 200, 28, { size: 18, bold: true, color: C.ink });
    text(slide, `p12-top-copy-${i}`, item[2], x, 240, 198, 44, { size: 14, color: C.muted, lineSpacing: 1.18 });
  });
  rule(slide, "p12-mid", 72, 310, 1136, 0, C.line2, 1);
  columnTitle(slide, "p12-provider", "프로바이더 전환 순서", 72, 340, 500, C.navy);
  const providers = [
    ["1", "OpenAI function calling", "OPENAI_API_KEY가 있을 때 사용"],
    ["2", "Anthropic tool use", "동일한 도구 정의를 변환해 사용"],
    ["3", "결정론적 템플릿", "키가 없거나 호출이 실패하면 자동 전환"],
  ];
  providers.forEach((p, i) => {
    const y = 390 + i * 64;
    text(slide, `p12-provider-num-${i}`, p[0], 72, y, 28, 26, { size: 15, bold: true, color: C.amber });
    text(slide, `p12-provider-head-${i}`, p[1], 112, y, 260, 26, { size: 17, bold: true, color: C.ink });
    text(slide, `p12-provider-copy-${i}`, p[2], 390, y, 250, 30, { size: 14, color: C.muted });
    rule(slide, `p12-provider-rule-${i}`, 72, y + 44, 568, 0, C.line, 1);
  });
  columnTitle(slide, "p12-guard", "고정된 차단선", 690, 340, 518, C.red);
  const guards = [
    ["금액 생성", "엔진 반환값만 답변에 사용"],
    ["근거 동반", "모든 엔진이 rationale 또는 reasons 반환"],
    ["추적 정보", "reply, toolCalls[], mode, provider를 응답에 기록"],
  ];
  guards.forEach((g, i) => {
    const y = 390 + i * 64;
    text(slide, `p12-guard-head-${i}`, g[0], 690, y, 130, 26, { size: 16, bold: true, color: C.red });
    text(slide, `p12-guard-copy-${i}`, g[1], 832, y, 376, 34, { size: 16, color: C.ink2 });
    rule(slide, `p12-guard-rule-${i}`, 690, y + 44, 518, 0, C.line, 1);
  });
  text(slide, "p12-end", "프로바이더가 바뀌어도 판정 수치는 동일합니다.", 690, 598, 518, 28, { size: 17, bold: true, color: C.navy });
}

// 13. Extraction
{
  const slide = addSlide(13, "정책 규칙 추출과 검증", "LLM이 만든 규칙 초안은 원문 인용과 스키마를 통과해야 검토 큐에 들어갑니다");
  const cols = [72, 416, 808];
  const widths = [286, 334, 400];
  const heads = ["원문 입력", "초안 검증", "검토 대기"];
  const bodies = [
    "정책 원문과 출처\n정책 식별자\n조회 시점\n코드포인트 기준 원문",
    "LLM이 RuleDraft와 근거 span 제안\n서버가 span을 원문과 대조\n스키마 오류 및 누락 검사\n한 항목이라도 실패하면 전체 폐기",
    "통과한 초안만 pending 저장\n실패 사유와 JSON 포인터 기록\n승인 전에는 시민 판정에서 제외\n시도, 지연, 결과를 감사 기록에 남김",
  ];
  cols.forEach((x, i) => {
    text(slide, `p13-num-${i}`, String(i + 1).padStart(2, "0"), x, 164, 48, 28, { size: 16, bold: true, color: C.amber });
    text(slide, `p13-head-${i}`, heads[i], x, 204, widths[i], 34, { size: 22, bold: true, color: C.ink });
    rule(slide, `p13-rule-${i}`, x, 252, widths[i] - 18, 0, i === 1 ? C.red : C.line2, i === 1 ? 3 : 1);
    text(slide, `p13-body-${i}`, bodies[i], x, 278, widths[i] - 18, 172, { size: 16, color: C.ink2, lineSpacing: 1.42 });
    if (i < 2) rule(slide, `p13-sep-${i}`, x + widths[i] + 16, 164, 0, 286, C.line, 1);
  });
  rule(slide, "p13-fail-left", 72, 490, 4, 114, C.red, 4);
  text(slide, "p13-fail-head", "실패를 별도 상태로 기록", 94, 488, 260, 28, { size: 18, bold: true, color: C.red });
  text(slide, "p13-fail-a", "span_not_in_text\n인용 구간이 원문과 일치하지 않음", 94, 530, 360, 66, { size: 16, color: C.ink2, lineSpacing: 1.22 });
  text(slide, "p13-fail-b", "span_missing\n값은 있으나 근거 구간이 없음", 470, 530, 330, 66, { size: 16, color: C.ink2, lineSpacing: 1.22 });
  text(slide, "p13-fail-note", "부분 저장을 허용하지 않습니다. 검증을 모두 통과한 초안만 사람이 검토할 수 있습니다.", 824, 510, 384, 84, { size: 17, bold: true, color: C.navy, lineSpacing: 1.26 });
  text(slide, "p13-offset", "span 오프셋 단위는 유니코드 코드포인트입니다.", 94, 616, 620, 20, { size: 12, color: C.faint });
}

// 14. Review and approval
{
  const slide = addSlide(14, "규칙 검토와 승인 권한", "규칙 변경은 검토 화면을 거쳐 서버 권한으로 승인되며 모든 결정은 기록됩니다");
  const stages = [
    ["01", "대기 큐", "pending 초안과 실패 사유 확인\n현장 데이터 신고는 별도 유형으로 구분"],
    ["02", "검토 화면", "원문과 인용 구간 대조\n필드 변경 전후와 회귀 영향도 확인"],
    ["03", "승인 또는 반려", "승인 시 불변 RuleVersion 생성\n반려 사유는 필수이며 두 결과 모두 기록"],
  ];
  stages.forEach((s, i) => {
    const x = 72 + i * 378;
    text(slide, `p14-stage-num-${i}`, s[0], x, 160, 46, 26, { size: 15, bold: true, color: C.amber });
    text(slide, `p14-stage-head-${i}`, s[1], x, 202, 330, 30, { size: 22, bold: true, color: C.ink });
    rule(slide, `p14-stage-rule-${i}`, x, 248, 330, 0, C.line2, 1);
    text(slide, `p14-stage-copy-${i}`, s[2], x, 274, 330, 96, { size: 16, color: C.ink2, lineSpacing: 1.38 });
    if (i < 2) rule(slide, `p14-stage-sep-${i}`, x + 354, 160, 0, 210, C.line, 1);
  });
  rule(slide, "p14-mid", 72, 398, 1136, 0, C.line2, 1);
  columnTitle(slide, "p14-role", "역할별 권한", 72, 430, 1136, C.navy);
  text(slide, "p14-role-a-head", "상담원", 72, 484, 150, 28, { size: 19, bold: true, color: C.ink });
  text(slide, "p14-role-a", "시민 판정의 내부 근거 확인\n데이터 이상 신고\n규칙 승인 API는 403으로 거부", 224, 482, 380, 94, { size: 16, color: C.ink2, lineSpacing: 1.34 });
  rule(slide, "p14-role-sep", 630, 468, 0, 122, C.line, 1);
  text(slide, "p14-role-b-head", "규칙관리자", 666, 484, 160, 28, { size: 19, bold: true, color: C.ink });
  text(slide, "p14-role-b", "대기 큐와 검토 화면 접근\n승인·반려 및 운영 지표 확인\n동시 승인 시 조건부 갱신으로 중복 방지", 842, 482, 366, 94, { size: 16, color: C.ink2, lineSpacing: 1.34 });
  text(slide, "p14-note", "권한 분리는 화면 구성이 아니라 서버의 세션과 API 검사로 강제합니다.", 72, 614, 1136, 24, { size: 15, bold: true, color: C.navy });
}

// 15. Provenance and audit
{
  const slide = addSlide(15, "데이터 출처와 감사 기록", "값의 출처와 검증 상태, 운영 이력을 함께 기록합니다");
  const tiers = [
    ["verified", C.green, "출처 문서를 열어\n대조한 값", "지역 시세 5개 필드\n국토교통부 실거래가 실측"],
    ["unverified", C.amber, "출처를 아직 특정하지\n못한 값", "관리비와 시장 위험도\n일부 정책 조건 및 금리 시드"],
    ["our_choice", C.navy2, "공표 준거가 없어\n서비스가 정한 값", "판정 임계와 가중치\n선택 사실을 화면과 계약에 표시"],
  ];
  tiers.forEach((t, i) => {
    const x = 72 + i * 378;
    rule(slide, `p15-tier-line-${i}`, x, 164, 74, 0, t[1], 5);
    text(slide, `p15-tier-name-${i}`, t[0], x, 188, 330, 30, { size: 20, bold: true, color: t[1] });
    text(slide, `p15-tier-def-${i}`, t[2], x, 234, 330, 48, { size: 16, bold: true, color: C.ink });
    text(slide, `p15-tier-ex-${i}`, t[3], x, 296, 330, 70, { size: 15, color: C.muted, lineSpacing: 1.28 });
    if (i < 2) rule(slide, `p15-tier-sep-${i}`, x + 354, 164, 0, 202, C.line, 1);
  });
  rule(slide, "p15-mid", 72, 398, 1136, 0, C.line2, 1);
  columnTitle(slide, "p15-audit", "감사 기록", 72, 430, 500, C.navy);
  text(slide, "p15-audit-copy", "AuditEvent는 추출, 승인, 반려, 신고를\n덧붙이기 방식으로 기록합니다.\n삭제 경로를 두지 않으며 사유 본문은 파일 로그에 쓰지 않습니다.", 72, 480, 510, 92, { size: 16, color: C.ink2, lineSpacing: 1.3 });
  columnTitle(slide, "p15-metric", "운영 지표", 660, 430, 548, C.navy);
  text(slide, "p15-metric-copy", "배치 상태, 데이터 신선도, 대기 큐,\nLLM 호출 성공률과 지연을 표시합니다.\n측정값이 없으면 0으로 채우지 않고 미수집 상태를 그대로 보여줍니다.", 660, 480, 548, 92, { size: 16, color: C.ink2, lineSpacing: 1.3 });
  text(slide, "p15-end", "출처를 찾지 못한 값과 서비스가 정한 값은 서로 다른 등급으로 표시합니다.", 72, 610, 1136, 28, { size: 17, bold: true, color: C.red });
}

// 16. Offline reproduction
{
  const slide = addSlide(16, "오프라인 동작과 시연 재현", "네트워크 차단 상태를 회차마다 확인하고 같은 시연 흐름을 세 번 다시 실행했습니다");
  const facts = [
    ["차단 확인", "각 회차의 5개 지점에서 무선 상태를 다시 확인"],
    ["대조 결과", "32개 항목을 비교해 불일치 0건, 장면 오류 0건"],
    ["허용된 실패", "외부 수집 실패 시 이전 값을 유지하고 계보를 stale로 변경"],
  ];
  facts.forEach((f, i) => {
    const x = 72 + i * 378;
    text(slide, `p16-fact-num-${i}`, String(i + 1).padStart(2, "0"), x, 162, 42, 26, { size: 15, bold: true, color: C.amber });
    text(slide, `p16-fact-head-${i}`, f[0], x, 202, 330, 28, { size: 20, bold: true, color: C.ink });
    text(slide, `p16-fact-copy-${i}`, f[1], x, 242, 330, 70, { size: 15, color: C.ink2, lineSpacing: 1.25 });
    if (i < 2) rule(slide, `p16-fact-sep-${i}`, x + 354, 162, 0, 150, C.line, 1);
  });
  rule(slide, "p16-mid", 72, 346, 1136, 0, C.line2, 1);
  columnTitle(slide, "p16-story", "재검증한 이유", 72, 378, 674, C.red);
  text(slide, "p16-story-copy", "처음에는 무선을 끄고 세 번 실행했지만, 회차 중 무선이 다시 활성화된 사실을 뒤늦게 확인했습니다. 이후 차단 방법을 바꾸고 각 회차의 시작과 주요 전환 지점에서 상태를 다시 확인했습니다. 기존 결과를 채택하지 않고 전 과정을 처음부터 다시 실행했습니다.", 72, 426, 656, 142, { size: 17, color: C.ink2, lineSpacing: 1.32 });
  columnTitle(slide, "p16-demo", "노트북 한 대에서 재현하는 순서", 780, 378, 428, C.navy);
  const demo = ["저장소와 픽스처 준비", "시민 판정 실행", "상담원 신고와 규칙 승인", "시민 화면에서 변경 확인"];
  demo.forEach((d, i) => {
    const y = 426 + i * 42;
    text(slide, `p16-demo-num-${i}`, String(i + 1), 780, y, 26, 24, { size: 14, bold: true, color: C.amber });
    text(slide, `p16-demo-copy-${i}`, d, 816, y, 392, 28, { size: 16, color: C.ink });
  });
  text(slide, "p16-end", "회차별 관측과 채택하지 않은 결과의 사유도 대본 문서에 남겼습니다.", 72, 614, 1136, 24, { size: 14, color: C.muted });
}

// 17. UX and stack
{
  const slide = addSlide(17, "화면 흐름과 기술 스택", "프로필 입력에서 결과 확인과 후속 상담까지 한 페이지에서 이어집니다");
  const imgBytes = await fs.readFile(path.join(workspaceDir, "output/evidence/home_compass_dashboard.png"));
  slide.images.add({
    blob: imgBytes,
    contentType: "image/png",
    alt: "Home_Compass 진단 결과 화면",
    fit: "contain",
    position: { left: 72, top: 160, width: 702, height: 395 },
  });
  rule(slide, "p17-image-bottom", 72, 562, 702, 0, C.line2, 1);
  text(slide, "p17-caption", "실제 실행 화면: 주거비 상한, 비용 비교, 정책 결과, 위험 점수", 72, 571, 702, 22, { size: 12, color: C.muted });
  columnTitle(slide, "p17-flow", "사용 흐름", 824, 160, 384, C.amber);
  text(slide, "p17-flow-copy", "1  프로필 입력\n2  결과 대시보드\n3  진단 결과에 질문", 824, 208, 384, 112, { size: 18, bold: true, color: C.ink, lineSpacing: 1.45 });
  rule(slide, "p17-side-mid", 824, 338, 384, 0, C.line, 1);
  columnTitle(slide, "p17-stack", "구현", 824, 366, 384, C.navy);
  text(slide, "p17-stack-copy", "프론트엔드  Vanilla HTML / CSS / JS\n백엔드  Python 3.11+ / FastAPI / SQLite\n차트  인라인 SVG\n테스트  pytest 단위·교차 검사\n실행  uvicorn + dev.bat", 824, 414, 384, 144, { size: 15, color: C.ink2, lineSpacing: 1.4 });
  text(slide, "p17-end", "빌드 도구와 CDN 의존성을 두지 않아 심사 환경에서 재현 가능한 실행을 우선했습니다.", 72, 620, 1136, 24, { size: 15, bold: true, color: C.navy });
}

// 18. Data disclosure
{
  const slide = addSlide(18, "프로토타입 수치와 데이터 한계", "항목별 출처와 검증 상태를 구분하고 확인되지 않은 값은 그대로 표시합니다");
  rule(slide, "p18-warning-rule", 72, 152, 4, 58, C.red, 4);
  text(slide, "p18-warning", "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.", 94, 158, 1114, 44, { size: 19, bold: true, color: C.red });
  const rows = [
    ["금리·한도·기간", "시연용 예시 수치입니다. 특정 금융회사의 실제 조건을 옮기거나 추정하지 않았습니다."],
    ["제도 요건", "연령, 무주택 등 공개된 일반 요건만 기술했습니다. 세부 기준은 기관과 시점에 따라 달라집니다."],
    ["통계 인용", "출처를 명시할 수 없는 통계는 인용하지 않았습니다. 필요한 경우 참고 자료의 범위만 표시했습니다."],
    ["지역 시세", "8개 필드 중 5개는 국토교통부 실거래가 실측값입니다. 관리비, 시장 위험도, 보증 가능성은 출처를 특정하지 못한 값입니다."],
  ];
  rows.forEach((r, i) => {
    const y = 246 + i * 76;
    text(slide, `p18-row-head-${i}`, r[0], 72, y, 220, 30, { size: 18, bold: true, color: C.ink });
    text(slide, `p18-row-copy-${i}`, r[1], 326, y, 882, 52, { size: 16, color: C.ink2, lineSpacing: 1.22 });
    rule(slide, `p18-row-rule-${i}`, 72, y + 60, 1136, 0, C.line, 1);
  });
  box(slide, "p18-structure", 72, 558, 1136, 84, { fill: C.grayWash, line: { style: "solid", fill: "none", width: 0 } });
  text(slide, "p18-structure-head", "데이터 구조의 필수 필드", 94, 576, 240, 24, { size: 15, bold: true, color: C.navy });
  text(slide, "p18-structure-code", "source: 출처 기관명     disclaimer: 항목별 고지     meta.disclaimer: 응답 단위 고지", 354, 575, 828, 26, { size: 15, color: C.ink });
  text(slide, "p18-structure-note", "출처와 고지가 없는 데이터는 화면에 노출되지 않습니다. 본 서비스는 금융상품 권유나 투자 자문을 제공하지 않습니다.", 94, 609, 1088, 22, { size: 13, color: C.muted });
}

// 19. Business fit and roadmap
{
  const slide = addSlide(19, "금융기관 적용 범위와 확장 순서", "주택금융 상담의 사전 진단 도구로 시작해 데이터, 상품, 사후 관리 범위를 단계적으로 넓힙니다");
  const impact = [
    ["주택금융 접점", "첫 주거를 준비하는 고객이 상담 전에 감당 가능한 범위와 정책 자격을 확인합니다."],
    ["상담 근거", "판정 결과와 이유를 함께 남겨 상담원이 같은 기준으로 설명할 수 있습니다."],
    ["도입 구조", "엔진과 LLM 연결을 분리해 내부망 모델과 기관별 상품 카탈로그로 교체할 수 있습니다."],
  ];
  impact.forEach((item, i) => {
    const x = 72 + i * 378;
    text(slide, `p19-impact-num-${i}`, String(i + 1).padStart(2, "0"), x, 162, 42, 24, { size: 14, bold: true, color: C.amber });
    text(slide, `p19-impact-head-${i}`, item[0], x, 200, 330, 30, { size: 21, bold: true, color: C.ink });
    text(slide, `p19-impact-copy-${i}`, item[1], x, 244, 330, 86, { size: 15, color: C.ink2, lineSpacing: 1.25 });
    if (i < 2) rule(slide, `p19-impact-sep-${i}`, x + 354, 162, 0, 168, C.line, 1);
  });
  rule(slide, "p19-mid", 72, 360, 1136, 0, C.line2, 1);
  label(slide, "p19-roadmap-label", "확장 순서", 72, 390, 120, C.navy);
  rule(slide, "p19-roadmap-base", 102, 448, 1034, 0, C.line2, 2);
  const roadmap = [
    ["현재", "프로토타입", "4대 엔진, 결과 화면, AI 상담"],
    ["다음", "데이터 연동", "공신력 있는 시세와 정책 데이터"],
    ["이후", "상품 연계", "기관별 주택금융 카탈로그와 내부망 모델"],
    ["운영", "사후 관리", "계약 이후 주거비 모니터링과 갱신 시점 재판정"],
  ];
  roadmap.forEach((r, i) => {
    const x = 72 + i * 284;
    box(slide, `p19-roadmap-node-${i}`, x + 24, 439, 18, 18, { geometry: "ellipse", fill: i === 0 ? C.amber : C.paper, line: { style: "solid", fill: i === 0 ? C.amber : C.line2, width: 2 } });
    text(slide, `p19-roadmap-stage-${i}`, r[0], x, 476, 80, 22, { size: 12, bold: true, color: C.amber });
    text(slide, `p19-roadmap-head-${i}`, r[1], x, 506, 250, 26, { size: 18, bold: true, color: C.ink });
    text(slide, `p19-roadmap-copy-${i}`, r[2], x, 541, 250, 60, { size: 14, color: C.muted, lineSpacing: 1.2 });
  });
  text(slide, "p19-end", "Home_Compass는 승인이나 판매를 대신하지 않습니다. 상담 전에 필요한 계산과 확인 항목을 같은 근거로 정리합니다.", 72, 622, 1136, 30, { size: 17, bold: true, color: C.navy });
}

if (presentation.slides.items.length !== 19) {
  throw new Error(`Expected 19 slides, got ${presentation.slides.items.length}`);
}

const stagingDir = path.join(TMP_DIR, ".codex-finalizer");
const publishDir = path.join(TMP_DIR, "validated");
await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(publishDir, { recursive: true });
const candidatePath = path.join(stagingDir, "candidate-technical-deck.pptx");
const validatedPath = path.join(publishDir, "validated-technical-deck.pptx");
const receiptPath = path.join(stagingDir, "technical-deck.validation.json");
await fs.rm(validatedPath, { force: true });
await fs.rm(receiptPath, { force: true });
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const result = await finalizePresentation({
  workspaceDir,
  candidatePath,
  finalPath: validatedPath,
  explicitTotalSlideCount: 19,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12191695,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  fontPolicy: {
    basis: "design",
    families: [FONT],
  },
  verifyArtifactToolImport: true,
  receiptPath,
});

await fs.copyFile(validatedPath, FINAL_PPTX);
console.log(JSON.stringify({ finalPath: FINAL_PPTX, result }, null, 2));
