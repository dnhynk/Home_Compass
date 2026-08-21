"""`ingest.market` — 시세 수집 파이프라인 (SPEC Part 3 · 3.1 · 10.2 3단계).

    python -m home_compass.ingest.market            # 실기동 (키가 있으면 실수집)
    python -m home_compass.ingest.market --demo     # 키 없이 전 과정을 보인다

흐름은 SPEC 3 그대로다 — **fetch -> 정규화 -> 이상치 검사 -> upsert + Provenance.**
각 단계가 별개 함수인 이유는 완료 기준 넷을 키 없이 증명하기 위해서다 (SPEC 9.2.1).

여기 **없는 것**이 곧 경계다 — LLM(이상치는 통계 기반이다) · 판정 · 화면.
"""

from __future__ import annotations

from .pipeline import (
    CONSTANT_KEYS,
    NO_COUNTERPART_FIELDS,
    RENT_DERIVED_FIELDS,
    TRADE_DERIVED_FIELDS,
    Deal,
    MarketFieldMappingError,
    MarketRunReport,
    Outlier,
    PairedRatio,
    RegionOutcome,
    Trade,
    area_band,
    collect_market,
    conversion_rate_pct,
    detect_outliers,
    jeonse_ratio_pct,
    median_krw,
    normalize_deals,
    normalize_trades,
    paired_conversion_rate_pct,
    paired_jeonse_ratio_pct,
    window_months,
)
from .source import (
    API_KEY_ENV,
    ENDPOINTS,
    SERVICE_KEY_ENV,
    SOURCE_NAMES,
    SOURCE_REFS,
    MarketAuthError,
    MarketServiceError,
    MarketSourceError,
    MolitClient,
    parse_items,
    resolve_api_key,
    total_count,
)

__all__ = [
    "CONSTANT_KEYS",
    "NO_COUNTERPART_FIELDS",
    "RENT_DERIVED_FIELDS",
    "TRADE_DERIVED_FIELDS",
    "Deal",
    "Trade",
    "Outlier",
    "PairedRatio",
    "RegionOutcome",
    "MarketRunReport",
    "MarketFieldMappingError",
    "MarketSourceError",
    "MarketAuthError",
    "MarketServiceError",
    "MolitClient",
    "API_KEY_ENV",
    "SERVICE_KEY_ENV",
    "ENDPOINTS",
    "SOURCE_NAMES",
    "SOURCE_REFS",
    "area_band",
    "collect_market",
    "conversion_rate_pct",
    "jeonse_ratio_pct",
    "paired_conversion_rate_pct",
    "paired_jeonse_ratio_pct",
    "detect_outliers",
    "median_krw",
    "normalize_deals",
    "normalize_trades",
    "window_months",
    "parse_items",
    "total_count",
    "resolve_api_key",
]
