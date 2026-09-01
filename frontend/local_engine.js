/* ============================================================
   Home_Compass — 로컬 판정 경로 (SPEC D-11 · 6.2 오프라인 정의)

   ── 이 파일이 무엇인가 ──────────────────────────────────────────────────────
   `backend/src/home_compass/engines/` 네 엔진의 **충실한 JS 이식**이다. 손으로 고른
   숫자가 한 개도 없다 — 상수·정책 규칙·지역 시세는 전부 `frontend/generated/`
   생성물에서 온다 (계약 결정 #34).

   D-11 이 이 경로를 없애지 않고 "생성물로 동기화"한 이유는 SPEC 6.2 오프라인 정의
   #2 다: **백엔드 없이도 화면이 뜬다 — 단, 판정 숫자는 생성물이 있을 때만 나온다.**

   ── 왜 상수만 갈아끼우지 않고 통째로 이식했는가 ──────────────────────────────
   예전 사본은 엔진 **구조 자체**가 백엔드와 달랐다 (시나리오 4종의 정체가 달랐고,
   밴드 판정식이 달랐고, 리스크 요인 목록이 달랐다). 그 구조에 생성물 상수를 꽂으면
   대응물이 없는 상수가 절반이라 이식이 성립하지 않고, 성립시키려고 빈 자리를 손으로
   메우는 순간 **두 경로가 조용히 다른 숫자를 낸다** — Part 0-A 에 기록된 사고 그
   자체이며 D-11 이 존재하는 이유다. 그래서 구조를 옮겼다.

   ── 무엇이 "같다"를 붙들고 있는가 ────────────────────────────────────────────
   주장이 아니라 파수병이다. `backend/tests/test_frontend_local_engine_equivalence.py`
   가 node 로 이 파일을 실행해 `contracts/regression_profiles.json` x 저장소 지역 전수를
   돌리고, 파이썬 `home_compass.engines.analyze()` 의 결과와 **숫자·상태 필드를 바이트
   비교**한다 (SPEC 5.3 의 numeric/text 분리 그대로). 어긋나면 CI 가 빨간불이다.

   ── 대응 관계 ────────────────────────────────────────────────────────────────
     engines/affordability.py   -> assessAffordability
     engines/eligibility.py     -> evaluatePolicy · evaluatePolicies
     engines/tco.py             -> guaranteeRatePctFor · sizeLoan · npv ·
                                   evaluateScenario · buildScenarios
     engines/risk.py            -> scanDepositRisk
     engines/__init__.py        -> analyze · loanOption · buildSummary · verdictCaveat ·
                                   guaranteeDepositCapFor · findRegion

   빌드툴·CDN 없이 `<script src>` 로 읽힌다 (SPEC 6.2 오프라인 정의 #1).
   ============================================================ */
(function (global) {
  'use strict';

  var FMT = global.HomeCompassFormat;

  /* ══════════════════════════════════════════════════════════
     0. 생성물 — 없으면 이 경로는 **동작하지 않는다** (D-11)

     `|| {}` 를 쓰지 않는다. 그 한 줄이 D-11 을 무효로 만든다 (계약 결정 #34).
     ══════════════════════════════════════════════════════════ */
  var ARTIFACTS = [
    { global: 'HOME_COMPASS_MODEL_CONSTANTS', file: 'generated/model_constants.js', label: '모델 상수' },
    { global: 'HOME_COMPASS_POLICY_RULES', file: 'generated/policy_rules.js', label: '승인된 정책 규칙' },
    { global: 'HOME_COMPASS_REGIONS', file: 'generated/regions.js', label: '지역 시세' },
    { global: 'HOME_COMPASS_CONTRACT_CONSTANTS', file: 'generated/contract_constants.js', label: '계약 상수' }
  ];

  /** 로컬 판정 경로가 성립하는가. 성립하지 않으면 **무엇이 없는지**를 함께 돌려준다. */
  function status() {
    var missing = [];
    if (!FMT) missing.push({ file: 'format.js', label: '포맷 함수' });
    ARTIFACTS.forEach(function (a) {
      if (!global[a.global]) missing.push({ file: a.file, label: a.label, global: a.global });
    });
    return { ready: missing.length === 0, missing: missing };
  }

  function requireArtifact(name) {
    var artifact = global[name];
    if (!artifact) {
      throw new Error(
        '생성물 ' + name + ' 이 없어 로컬 판정을 할 수 없습니다. ' +
        '기본값으로 대체하지 않습니다 (SPEC D-11).'
      );
    }
    return artifact;
  }

  /** 모델 상수 하나. 없으면 던진다 — 파이썬 `constants[key]` 의 `KeyError` 자리다. */
  function K(key) {
    var entries = requireArtifact('HOME_COMPASS_MODEL_CONSTANTS').entries;
    if (!Object.prototype.hasOwnProperty.call(entries, key)) {
      throw new Error('모델 상수가 생성물에 없습니다: ' + key + ' (SPEC 5.1.1 fail-closed)');
    }
    return entries[key].value;
  }

  function constantProvenance(key) {
    return requireArtifact('HOME_COMPASS_MODEL_CONSTANTS').entries[key].provenance;
  }

  /* `meta.disclaimer` 는 `home_compass/common.py` 의 `DISCLAIMER` 다. 판정 숫자를 바꾸는
     값이 아니라 화면 문구이므로 `ModelConstant` 대상이 아니고(SPEC 5.1.2 비대상),
     생성물에도 독립 항목으로는 실리지 않는다. 대신 **문자열이 같은지를 테스트가
     직접 붙든다** (`test_frontend_local_engine_equivalence.py`). */
  var DISCLAIMER =
    '프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.';

  /* ══════════════════════════════════════════════════════════
     1. 파이썬 `common.py` 대응물 (포맷은 format.js 가 정본)
     ══════════════════════════════════════════════════════════ */
  function money(v) { return FMT.money(v); }
  function pct(v, d) { return FMT.pct(v, d); }
  function safeInt(v, d) { return FMT.safeInt(v, d); }
  function roundHalf(v, d) { return FMT.roundHalf(v, d); }

  /** 파이썬 `common.floor_to`. */
  function floorTo(value, unit) {
    var step = unit == null ? 10000 : unit;
    if (!(value > 0)) return 0;
    return Math.floor(value / step) * step;
  }

  /** 파이썬 `common.ratio` — 0분모는 예외가 아니라 0.0 이다. */
  function ratio(numerator, denominator) {
    if (!denominator) return 0.0;
    return Number(numerator) / Number(denominator);
  }

  /* ══════════════════════════════════════════════════════════
     2. 활성 규칙 · 지역 (SPEC 2.3 술어를 **소비자가 자기 시각으로** 적용한다)
     ══════════════════════════════════════════════════════════ */

  /**
   * 생성물은 승인된 `RuleVersion` **전부**를 담는다. 생성 시각으로 미리 걸러 두면
   * 생성물이 「언제 생성됐나」에 의존하고, 시행일이 미래인 규칙은 그 날이 와도 영영
   * 나오지 않는다 (계약 결정 #34).
   */
  function activeRuleVersions(nowMs) {
    return requireArtifact('HOME_COMPASS_POLICY_RULES').ruleVersions.filter(function (v) {
      var rv = v.ruleVersion;
      return (rv.effective_from === null || Date.parse(rv.effective_from) <= nowMs)
          && (rv.effective_to === null || nowMs < Date.parse(rv.effective_to));
    });
  }

  function activePolicies(nowMs) {
    return activeRuleVersions(nowMs).map(function (v) { return v.payload; });
  }

  /** 생성물의 지역 레코드 전부. `payload` 가 엔진 입력이고 계보는 그 옆에 있다. */
  function regionRecords() {
    return requireArtifact('HOME_COMPASS_REGIONS').regions;
  }

  /** 파이썬 `engines.find_region`. */
  function findRegion(regionCode, regions) {
    var code = String(regionCode == null ? '' : regionCode);
    for (var i = 0; i < regions.length; i++) {
      if (regions[i].code === code) return regions[i];
    }
    return null;
  }

  /* ══════════════════════════════════════════════════════════
     3. E1 — 주거지불능력 (engines/affordability.py)
     ══════════════════════════════════════════════════════════ */

  /** 파이썬 `affordability.living_cost_for`. 생성물의 키는 문자열이다($objectKeys). */
  function livingCostFor(householdSize) {
    var byHousehold = K('affordability.living_cost_by_household');
    var extraPerPerson = K('affordability.living_cost_extra_per_person');
    var size = Math.max(1, safeInt(householdSize, 1) || 1);
    if (Object.prototype.hasOwnProperty.call(byHousehold, String(size))) {
      return byHousehold[String(size)];
    }
    var largest = Math.max.apply(null, Object.keys(byHousehold).map(Number));
    return byHousehold[String(largest)] + (size - largest) * extraPerPerson;
  }

  /** 파이썬 `affordability.assess_affordability`. */
  function assessAffordability(input) {
    var housingCostRatioCap = K('affordability.housing_cost_ratio_cap');
    var recommendedHaircut = K('affordability.recommended_haircut');
    var bufferRatio = K('affordability.buffer_ratio');
    var netIncomeFromAnnual = K('affordability.net_income_from_annual');
    var safeCapRatio = K('affordability.safe_cap_ratio');
    var safeDebtRatio = K('affordability.safe_debt_ratio');
    var cautionCapRatio = K('affordability.caution_cap_ratio');
    var cautionDebtRatio = K('affordability.caution_debt_ratio');

    var rationale = [];

    var netIncome = safeInt(input.monthlyNetIncomeKRW);
    var annualIncome = safeInt(input.annualIncomeKRW);
    var debt = safeInt(input.existingDebtMonthlyKRW);
    var assets = safeInt(input.liquidAssetsKRW);
    var size = Math.max(1, safeInt(input.householdSize, 1) || 1);

    if (netIncome <= 0 && annualIncome > 0) {
      netIncome = Math.trunc(annualIncome / 12 * netIncomeFromAnnual);
      rationale.push(
        '월 실수령액이 입력되지 않아 연소득 ' + money(annualIncome) + '의 ' +
        pct(netIncomeFromAnnual * 100, 0) + '를 12개월로 나눈 ' +
        money(netIncome) + '을 가처분소득으로 추정했습니다.'
      );
    }

    var livingCost = livingCostFor(size);
    var bufferAmount = Math.trunc(netIncome * bufferRatio);

    var ratioCap = netIncome * housingCostRatioCap;
    var residualCap = netIncome - livingCost - debt - bufferAmount;

    var maxCost = netIncome > 0 ? floorTo(Math.min(ratioCap, residualCap)) : 0;
    var recommended = floorTo(maxCost * recommendedHaircut);

    var capRatio = ratio(maxCost, netIncome);
    var debtRatio = ratio(debt, netIncome);

    var band;
    if (netIncome <= 0) band = 'risk';
    else if (maxCost <= 0) band = 'risk';
    else if (capRatio >= safeCapRatio && debtRatio <= safeDebtRatio) band = 'safe';
    else if (capRatio >= cautionCapRatio && debtRatio <= cautionDebtRatio) band = 'caution';
    else band = 'risk';

    if (netIncome <= 0) {
      rationale.push(
        '소득 정보가 없어 감당 가능 주거비를 산출할 수 없습니다. ' +
        '월 실수령액 또는 연소득을 입력해 주세요.'
      );
    } else {
      rationale.push(
        '가처분소득 ' + money(netIncome) + ' 중 주거비 상한을 ' +
        pct(housingCostRatioCap * 100, 0) + '로 설정했습니다.'
      );
      rationale.push(
        size + '인 가구 기준 비주거 생활비 ' + money(livingCost) + ', ' +
        '기존 부채 상환 ' + money(debt) + ', 비상자금 버퍼 ' +
        money(bufferAmount) + '(소득의 ' + pct(bufferRatio * 100, 0) + ')를 차감하면 ' +
        '주거비로 쓸 수 있는 잔여 여력은 ' + money(Math.max(residualCap, 0)) + '입니다.'
      );
      if (residualCap < ratioCap) {
        rationale.push(
          '소득 대비 비율보다 실제 잔여 여력이 더 빠듯해, 잔여 여력 기준으로 ' +
          '상한을 ' + money(maxCost) + '으로 확정했습니다.'
        );
      } else {
        rationale.push(
          '잔여 여력(' + money(Math.max(residualCap, 0)) + ')보다 소득 대비 비율 상한이 ' +
          '낮아, 상한을 ' + money(maxCost) + '으로 확정했습니다.'
        );
      }
      rationale.push(
        '권장액은 상한 ' + money(maxCost) + '의 ' + pct(recommendedHaircut * 100, 0) + '인 ' +
        money(recommended) + '입니다. 상한에 붙여 계약하지 않도록 ' +
        pct((1 - recommendedHaircut) * 100, 0) + '의 여유를 둔 값이며, ' +
        '이 여유폭에는 공표 준거가 없는 우리 기준입니다.'
      );
      if (debtRatio > safeDebtRatio) {
        rationale.push(
          '기존 부채 상환액이 소득의 ' + pct(debtRatio * 100) + '로 높아 ' +
          '주거비 여력이 크게 제한됩니다. 부채 상환 계획을 먼저 점검하세요.'
        );
      }
    }

    rationale.push({
      safe: '소득 대비 주거비 여력이 안정적인 구간(safe)입니다.',
      caution: '주거비 여력이 빠듯해 주의가 필요한 구간(caution)입니다.',
      risk: '현재 소득·부채 구조로는 주거비 부담이 위험한 구간(risk)입니다.'
    }[band]);

    if (assets > 0) {
      rationale.push('보유 유동자산 ' + money(assets) + '은 보증금 조달 여력 판단에 사용됩니다.');
    }

    rationale.push(DISCLAIMER);

    /* F-1 (SPEC 5.2.1) — `schwabeIndexPct` 는 **여기에 없다.** 권장액을 소득으로 나눈
       값은 측정값이 아니라 상한 규칙의 되풀이였다. 대체 필드도 두지 않는다. */
    return {
      maxMonthlyHousingCostKRW: maxCost,
      recommendedMonthlyHousingCostKRW: recommended,
      band: band,
      breakdown: {
        netIncome: netIncome,
        livingCost: livingCost,
        existingDebt: debt,
        buffer: bufferAmount
      },
      rationale: rationale
    };
  }

  /* ══════════════════════════════════════════════════════════
     4. E2 — 정책 적격성 (engines/eligibility.py)

     ★ 정책마다 `rule` 함수를 쓰지 않는다. 요건 숫자를 함수 몸통에 박으면 그 함수는
       백엔드 엔진과 별개로 자라고, 그것이 D-11 이 없애려는 두 번째 판정 경로다
       (계약 결정 #34 「함수를 내보내지 않는다」). 아래는 `criteria` 8종을
       **데이터로 해석**한다 — `eligibility.py` 와 같은 순서·같은 의미다.
     ══════════════════════════════════════════════════════════ */
  var POLICY_STATUS_ORDER = { eligible: 0, conditional: 1, ineligible: 2 };

  function evaluatePolicy(profile, policy, regionName) {
    var boundaryMargin = K('eligibility.boundary_margin');
    var ageCapImminentYears = K('eligibility.age_cap_imminent_years');
    var ageMaxUnlimited = K('eligibility.age_max_unlimited_sentinel');
    var amountUnlimited = K('eligibility.amount_unlimited_sentinel_krw');

    var crit = policy.criteria || {};
    var reasons = [];
    var failures = [];
    var caveats = (policy.conditionalChecks || []).slice();

    var age = safeInt(profile.age);
    var annualIncome = safeInt(profile.annualIncomeKRW);
    var assets = safeInt(profile.liquidAssetsKRW);
    var regionCode = String(profile.regionCode || '');
    var isHomeless = Boolean(profile.isHomeless);
    var isNewlywed = Boolean(profile.isNewlywed);
    var isSME = Boolean(profile.isSMEEmployee);

    /* --- 연령 ---
       상한과 하한을 **각각** 판단한다. 소득·자산이 그렇듯 한쪽의 부재가 다른 쪽의 검사를
       지우면 안 된다. 무제한 센티넬은 상한에만 뜻이 있다 — `ageMax` 가 200 이어도
       `ageMin` 은 여전히 거른다 (`newlywed_jeonse` 가 19/200 이다).

       `ageMin` 0 은 "선언되지 않음"과 같게 다룬다. `age` 는 `safeInt` 를 지나 항상 0
       이상이므로 `age >= 0` 은 항등식이고, 아무도 거르지 못하는 검사에 사유 줄을 내면
       "만 0세 이상 요건 충족" 같은 소음만 남는다 (`hug_deposit_guarantee` 가 0/200 이다).

       `eligibility.py` 의 같은 블록과 **줄 단위로 같은 판단**을 해야 한다. 두 벌이 갈리면
       시민은 온라인과 오프라인에서 다른 판정을 본다 (D-11). */
    var ageMin = crit.ageMin;
    var ageMax = crit.ageMax;
    var hasAgeMin = ageMin != null && ageMin > 0;
    var hasAgeMax = ageMax != null && ageMax < ageMaxUnlimited;
    var ageLabel = '';
    if (hasAgeMin && hasAgeMax) {
      ageLabel = '만 ' + ageMin + '~' + ageMax + '세';
    } else if (hasAgeMin) {
      ageLabel = '만 ' + ageMin + '세 이상';
    } else if (hasAgeMax) {
      ageLabel = '만 ' + ageMax + '세 이하';
    }
    if (ageLabel) {
      if ((hasAgeMin && age < ageMin) || (hasAgeMax && age > ageMax)) {
        var ageMsg = ageLabel + ' 요건 미충족 (' + age + '세)';
        reasons.push(ageMsg);
        failures.push(ageMsg);
      } else {
        reasons.push(ageLabel + ' 요건 충족 (' + age + '세)');
        /* 임박 caveat 은 상한이 실재할 때만 뜻이 있다. */
        if (hasAgeMax && ageMax - age <= ageCapImminentYears) {
          caveats.push('연령 상한(' + ageMax + '세)에 임박했습니다. 신청 시점 기준으로 재확인이 필요합니다.');
        }
      }
    }

    /* --- 소득 --- */
    var incomeCap = crit.annualIncomeMaxKRW;
    if (incomeCap != null && incomeCap < amountUnlimited) {
      if (annualIncome <= incomeCap) {
        reasons.push('연소득 ' + money(incomeCap) + ' 이하 충족 (' + money(annualIncome) + ')');
        if (ratio(annualIncome, incomeCap) >= 1 - boundaryMargin) {
          caveats.push(
            '연소득이 기준선(' + money(incomeCap) + ')의 ' +
            pct(ratio(annualIncome, incomeCap) * 100) + ' ' +
            '수준으로 경계값에 가깝습니다. 소득 산정 방식에 따라 결과가 달라질 수 있습니다.'
          );
        }
      } else {
        var incomeMsg = '연소득 ' + money(incomeCap) + ' 이하 요건 미충족 (' + money(annualIncome) + ')';
        reasons.push(incomeMsg);
        failures.push(incomeMsg);
      }
    }

    /* --- 자산 --- */
    var assetCap = crit.assetMaxKRW;
    if (assetCap != null && assetCap < amountUnlimited) {
      if (assets <= assetCap) {
        reasons.push('순자산 ' + money(assetCap) + ' 이하 충족 (' + money(assets) + ')');
      } else {
        var assetMsg = '순자산 ' + money(assetCap) + ' 이하 요건 미충족 (' + money(assets) + ')';
        reasons.push(assetMsg);
        failures.push(assetMsg);
      }
    }

    /* --- 불리언 요건 --- */
    if (crit.requireHomeless) {
      if (isHomeless) {
        reasons.push('무주택 요건 충족');
      } else {
        reasons.push('무주택 요건 미충족 (주택 보유)');
        failures.push('무주택 요건 미충족 (주택 보유)');
      }
    }

    if (crit.requireNewlywed) {
      if (isNewlywed) {
        reasons.push('신혼부부(혼인 요건) 충족');
      } else {
        reasons.push('신혼부부 전용 상품으로 혼인 요건 미충족');
        failures.push('신혼부부 전용 상품으로 혼인 요건 미충족');
      }
    }

    if (crit.requireSME) {
      if (isSME) {
        reasons.push('중소·중견기업 재직 요건 충족');
      } else {
        reasons.push('중소·중견기업 재직 요건 미충족');
        failures.push('중소·중견기업 재직 요건 미충족');
      }
    }

    /* --- 지역 --- */
    var prefixes = crit.regionPrefixes || [];
    if (prefixes.length) {
      var where = regionName || regionCode || '선택 지역';
      var matched = prefixes.some(function (p) { return regionCode.indexOf(p) === 0; });
      if (matched) {
        reasons.push('거주 지역 요건 충족 (' + where + ')');
      } else {
        var regionMsg = '해당 지자체 거주자 전용 제도로 지역 요건 미충족 (' + where + ')';
        reasons.push(regionMsg);
        failures.push(regionMsg);
      }
    }

    if (!reasons.length) reasons.push('별도 자격 제한이 없는 제도입니다.');

    var status;
    if (failures.length) status = 'ineligible';
    else if (caveats.length) status = 'conditional';
    else status = 'eligible';

    if (status === 'conditional') reasons = reasons.concat(caveats);

    /* `notes` 는 설명일 뿐 판정을 바꾸지 않는다. */
    reasons = reasons.concat(policy.notes || []);

    return {
      id: policy.id || '',
      name: policy.name || '',
      category: policy.category || '',
      status: status,
      reasons: reasons,
      maxAmountKRW: safeInt(policy.maxAmountKRW),
      rateRangePct: (policy.rateRangePct || [0.0, 0.0]).slice(),
      source: policy.source || '',
      disclaimer: policy.disclaimer || ''
    };
  }

  /** 파이썬 `eligibility.evaluate_policies`. 정렬 키·안정성까지 같다. */
  function evaluatePolicies(profile, policies, regionName) {
    var evaluated = (policies || []).map(function (p) {
      return evaluatePolicy(profile, p, regionName);
    });
    stableSort(evaluated, function (a, b) {
      var byStatus = (POLICY_STATUS_ORDER[a.status] == null ? 3 : POLICY_STATUS_ORDER[a.status])
                   - (POLICY_STATUS_ORDER[b.status] == null ? 3 : POLICY_STATUS_ORDER[b.status]);
      if (byStatus !== 0) return byStatus;
      return (-a.maxAmountKRW) - (-b.maxAmountKRW);
    });

    var counts = { eligible: 0, conditional: 0, ineligible: 0 };
    evaluated.forEach(function (p) { counts[p.status] += 1; });

    var rationale = [
      '총 ' + evaluated.length + '개 제도를 검토해 적격 ' + counts.eligible + '건, ' +
      '조건부 ' + counts.conditional + '건, 부적격 ' + counts.ineligible + '건으로 판정했습니다.'
    ];

    evaluated.filter(function (p) { return p.status === 'eligible'; }).slice(0, 2)
      .forEach(function (p) {
        rationale.push('[' + p.name + '] 적격 — ' + p.reasons.slice(0, 2).join(' / '));
      });

    evaluated.filter(function (p) { return p.status === 'conditional'; }).slice(0, 2)
      .forEach(function (p) {
        rationale.push('[' + p.name + '] 조건부 — 추가 확인이 필요합니다: ' + p.reasons[p.reasons.length - 1]);
      });

    if (counts.eligible === 0 && counts.conditional === 0) {
      rationale.push(
        '현재 프로필로 즉시 적용 가능한 제도가 없습니다. ' +
        '소득·자산·연령 요건을 다시 확인하거나 지역을 변경해 보세요.'
      );
    }

    rationale.push(
      '정책 조건은 공개된 일반 요건을 단순화한 예시이며, 실제 심사 기준은 ' +
      '각 기관 공고를 따릅니다.'
    );

    return { policies: evaluated, rationale: rationale };
  }

  /* ══════════════════════════════════════════════════════════
     5. E3 — 전월세 총비용 (engines/tco.py)
     ══════════════════════════════════════════════════════════ */

  /** 파이썬 `tco._npv`. */
  function npv(monthlyCost, months, discountRatePct) {
    if (monthlyCost <= 0) return 0;
    var monthlyRate = Math.pow(1 + discountRatePct / 100, 1 / 12) - 1;
    if (monthlyRate <= 0) return roundHalf(monthlyCost * months, 0);
    var factor = (1 - Math.pow(1 + monthlyRate, -months)) / monthlyRate;
    return roundHalf(monthlyCost * factor, 0);
  }

  /** 파이썬 `tco.guarantee_rate_pct_for` — 24칸 요율표에서 구간 최고요율 (F-3). */
  function guaranteeRatePctFor(depositKRW) {
    var table = K('tco.guarantee_rate_table');
    var rule = K('tco.guarantee_rate_unknown_axis_rule');
    if (rule !== 'bracket_max') {
      throw new Error('알 수 없는 보증료율 조회 규칙입니다: ' + rule);
    }
    var deposit = safeInt(depositKRW);
    var bounds = [];
    table.forEach(function (row) {
      if (row.depositMaxKRW !== null && bounds.indexOf(row.depositMaxKRW) === -1) {
        bounds.push(row.depositMaxKRW);
      }
    });
    bounds.sort(function (a, b) { return a - b; });
    var bracket = null;
    for (var i = 0; i < bounds.length; i++) {
      if (deposit <= bounds[i]) { bracket = bounds[i]; break; }
    }
    var cells = table.filter(function (row) { return row.depositMaxKRW === bracket; })
                     .map(function (row) { return row.ratePct; });
    if (!cells.length) {
      throw new Error('보증료율표에 보증금액 ' + deposit + ' 이 속할 구간이 없습니다.');
    }
    return Math.max.apply(null, cells);
  }

  /** 파이썬 `tco.size_loan`. */
  function sizeLoan(depositKRW, liquidAssetsKRW, loanCapKRW) {
    var deposit = safeInt(depositKRW);
    var needed = Math.max(0, deposit - safeInt(liquidAssetsKRW));
    var ceiling = Math.min(Math.trunc(deposit * K('tco.jeonse_ltv')), safeInt(loanCapKRW));
    return floorTo(Math.min(needed, ceiling), K('tco.deposit_rounding_unit_krw'));
  }

  /** 파이썬 `tco.evaluate_scenario`. */
  function evaluateScenario(args) {
    var horizonYears = K('tco.horizon_years');
    var horizonMonths = horizonYears * 12;
    var opportunityRatePct = K('tco.opportunity_rate_pct');
    var discountRatePct = K('tco.discount_rate_pct');

    var deposit = safeInt(args.depositKRW);
    var rent = safeInt(args.monthlyRentKRW);
    var maintenance = safeInt(args.maintenanceFeeKRW);
    var loan = Math.min(safeInt(args.loanAmountKRW), deposit);
    var rate = Math.max(0.0, Number(args.loanRatePct || 0.0));
    var assets = safeInt(args.liquidAssetsKRW);
    var affMax = safeInt(args.affordableMaxKRW);
    var affRec = safeInt(args.affordableRecommendedKRW);
    var netIncome = safeInt(args.monthlyNetIncomeKRW);

    var ownCapital = Math.max(0, deposit - loan);
    var capitalShortfall = Math.max(0, ownCapital - assets);

    /* F-5 · F-4 — 확인하는 것은 가입요건 셋 중 **보증금 상한 하나뿐**이다. */
    var guaranteeCap = safeInt(args.guaranteeDepositCapKRW);
    var useInsurance = args.insuranceEnabled && deposit > 0 && deposit <= guaranteeCap;
    var guaranteeRatePct = guaranteeRatePctFor(deposit);

    var components = {
      interest: roundHalf(loan * rate / 100 * horizonYears, 0),
      rent: rent * horizonMonths,
      maintenance: maintenance * horizonMonths,
      opportunityCost: roundHalf(ownCapital * opportunityRatePct / 100 * horizonYears, 0),
      insurance: useInsurance ? roundHalf(deposit * guaranteeRatePct / 100 * horizonYears, 0) : 0
    };
    var tco = components.interest + components.rent + components.maintenance +
              components.opportunityCost + components.insurance;
    var monthlyEquivalent = floorTo(tco / horizonMonths, K('tco.monthly_rounding_unit_krw'));
    var presentValue = npv(tco / horizonMonths, horizonMonths, discountRatePct);

    /* F-1 (SPEC 5.2.1) — 실제 주거비 / 소득. **상한이 없다.**
       소득이 0이면 비율은 정의되지 않으므로 `null` 이다. 0.0 으로 메우지 않는다. */
    var schwabeIndexPct = netIncome > 0
      ? roundHalf(monthlyEquivalent / netIncome * 100, 1)
      : null;

    var verdict;
    if (affMax <= 0) verdict = 'unaffordable';
    else if (monthlyEquivalent <= affRec) verdict = 'affordable';
    else if (monthlyEquivalent <= affMax) verdict = 'stretch';
    else verdict = 'unaffordable';

    var affordScore;
    if (affRec > 0) {
      var over = ratio(monthlyEquivalent, affRec);
      var affordWeight = K('tco.fit_afford_weight');
      affordScore = over <= 1
        ? affordWeight
        : Math.max(0.0, affordWeight - (over - 1) * K('tco.fit_afford_overrun_slope'));
    } else {
      affordScore = 0.0;
    }

    var capitalWeight = K('tco.fit_capital_weight');
    var capitalScore = ownCapital <= 0
      ? capitalWeight
      : capitalWeight * (1 - Math.min(1.0, ratio(capitalShortfall, ownCapital)));

    var preferenceScore = (args.preferredType === 'any' || args.preferredType === args.type)
      ? K('tco.fit_preference_match_score')
      : K('tco.fit_preference_mismatch_score');
    var fitScore = Math.trunc(Math.max(0, Math.min(100,
      roundHalf(affordScore + capitalScore + preferenceScore, 0))));

    var rationale = [
      '보증금 ' + money(deposit) + ', 월세 ' + money(rent) + ', 관리비 ' + money(maintenance) +
      ' 기준 ' + horizonYears + '년 총비용은 ' + money(tco) + '이며 월 환산 ' +
      money(monthlyEquivalent) + '입니다.'
    ];
    if (loan > 0) {
      rationale.push(
        '대출 ' + money(loan) + '에 연 ' + pct(rate, 2) + '를 적용해 ' + horizonYears + '년 이자 ' +
        money(components.interest) + '이 발생합니다.'
      );
    } else {
      rationale.push('대출 없이 자기자본으로 조달하는 시나리오라 이자 비용이 없습니다.');
    }

    if (components.opportunityCost > 0) {
      rationale.push(
        '보증금에 묶이는 자기자본 ' + money(ownCapital) + '의 기회비용을 연 ' +
        pct(opportunityRatePct, 1) + '로 계산해 ' + money(components.opportunityCost) + '을 ' +
        '총비용에 포함했습니다. 보증금 자체는 계약 종료 시 돌려받으므로 비용이 아닙니다.'
      );
    }
    if (components.insurance > 0) {
      rationale.push(
        '전세보증금반환보증 보증료율은 HUG 공시 요율표에서 보증금액 ' + money(deposit) + ' ' +
        '구간의 연 ' + pct(guaranteeRatePct, 3) + '를 적용해 ' + horizonYears + '년 ' +
        money(components.insurance) + '을 반영했습니다. 요율표는 주택유형(아파트/기타)과 ' +
        '부채비율에 따라 다시 갈리는데 두 값이 입력에 없어 해당 구간의 최고요율을 ' +
        '적용했습니다. 실제 요율은 이보다 낮을 수 있습니다.'
      );
      rationale.push(
        '가입요건 중 여기서 확인한 것은 보증금 상한 하나뿐입니다. 선순위채권이 ' +
        '주택가액의 60% 이내인지, 보증한도(주택가격 x 90% - 선순위채권)를 넘지 않는지는 ' +
        '물건별로 달라 이 도구가 판단하지 않습니다.'
      );
    } else if (args.insuranceEnabled && deposit > guaranteeCap) {
      rationale.push(
        '보증금 ' + money(deposit) + '이 전세보증금반환보증 가입 가능 상한 ' +
        money(guaranteeCap) + '을 넘어 보증료를 계상하지 않았습니다. ' +
        '보증에 가입할 수 없다는 뜻이므로 총비용이 낮은 것이 유리한 조건은 아닙니다.'
      );
    }
    if (capitalShortfall > 0) {
      rationale.push(
        '필요 자기자본 ' + money(ownCapital) + ' 대비 보유 자산이 ' +
        money(capitalShortfall) + ' 부족합니다. 추가 대출 한도 확인이나 ' +
        '보증금이 낮은 대안을 함께 검토하세요.'
      );
    }
    rationale.push(
      '현재가치(NPV, 실질할인율 연 ' + pct(discountRatePct, 1) + ')는 ' + money(presentValue) + '입니다.'
    );
    if (netIncome > 0) {
      rationale.push(
        '이 안의 슈바베지수(월 주거비 ÷ 월 실수령액)는 ' +
        pct(schwabeIndexPct) + '입니다 — 월 실수령액 ' + money(netIncome) + ' 기준 ' +
        '월 환산비용 ' + money(monthlyEquivalent) + '의 비중이며, 권장액이 아니라 ' +
        '이 시나리오의 실제 비용을 잰 값입니다.'
      );
    }
    rationale.push({
      affordable: '월 환산비용이 권장 주거비 ' + money(affRec) + ' 이내여서 감당 가능합니다.',
      stretch: '월 환산비용이 권장액 ' + money(affRec) + '은 넘지만 상한 ' + money(affMax) +
               ' 이내여서 무리하면 가능한 구간입니다.',
      unaffordable: '월 환산비용이 감당 가능 상한 ' + money(affMax) + '을 초과해 권장하지 않습니다.'
    }[verdict]);

    return {
      id: args.id,
      label: args.label,
      type: args.type,
      depositKRW: deposit,
      monthlyRentKRW: rent,
      loanAmountKRW: loan,
      loanRatePct: roundHalf(rate, 2),
      monthlyEquivalentCostKRW: monthlyEquivalent,
      tco5yKRW: tco,
      npv5yKRW: presentValue,
      components: components,
      fitScore: fitScore,
      schwabeIndexPct: schwabeIndexPct,
      verdict: verdict,
      rationale: rationale
    };
  }

  /** 파이썬 `tco.build_scenarios`. 네 시나리오의 정체와 순서까지 같다. */
  function buildScenarios(region, profile, affordability, jeonseLoan, monthlyLoan,
                          preferredType, guaranteeDepositCapKRW) {
    var horizonYears = K('tco.horizon_years');
    var fallbackJeonseRatePct = K('tco.fallback_jeonse_rate_pct');
    var opportunityRatePct = K('tco.opportunity_rate_pct');
    var depositRoundingUnit = K('tco.deposit_rounding_unit_krw');
    var monthlyRoundingUnit = K('tco.monthly_rounding_unit_krw');

    var assets = safeInt(profile.liquidAssetsKRW);
    var affMax = safeInt(affordability.maxMonthlyHousingCostKRW);
    var affRec = safeInt(affordability.recommendedMonthlyHousingCostKRW);
    var netIncome = safeInt((affordability.breakdown || {}).netIncome);

    var jeonseMedian = safeInt(region.jeonseMedianKRW);
    var stdDeposit = safeInt(region.monthlyDepositKRW);
    var stdRent = safeInt(region.monthlyRentKRW);
    var maintenance = safeInt(region.maintenanceFeeKRW);
    var conversion = Number(region.conversionRatePct || K('tco.fallback_conversion_rate_pct'));
    var guaranteeOK = region.guaranteeAvailable === undefined
      ? true : Boolean(region.guaranteeAvailable);

    var jeonseCap, jeonseRate, jeonseLabel;
    if (jeonseLoan) {
      jeonseCap = safeInt(jeonseLoan.maxAmountKRW);
      jeonseRate = Number(jeonseLoan.ratePct || fallbackJeonseRatePct);
      jeonseLabel = '전세 + ' + (jeonseLoan.name || '전세자금대출');
    } else {
      jeonseCap = Math.trunc(jeonseMedian * K('tco.jeonse_ltv'));
      jeonseRate = fallbackJeonseRatePct;
      jeonseLabel = '전세 + 일반 전세자금대출(예시 금리)';
    }

    var monthlyCap, monthlyRate, monthlyLabelSuffix;
    if (monthlyLoan) {
      monthlyCap = safeInt(monthlyLoan.maxAmountKRW);
      monthlyRate = Number(monthlyLoan.ratePct || fallbackJeonseRatePct);
      monthlyLabelSuffix = ' + ' + (monthlyLoan.name || '보증금대출');
    } else {
      monthlyCap = 0;
      monthlyRate = fallbackJeonseRatePct;
      monthlyLabelSuffix = '';
    }

    function common(extra) {
      return Object.assign({
        maintenanceFeeKRW: maintenance,
        liquidAssetsKRW: assets,
        affordableMaxKRW: affMax,
        affordableRecommendedKRW: affRec,
        monthlyNetIncomeKRW: netIncome,
        preferredType: preferredType,
        insuranceEnabled: guaranteeOK,
        guaranteeDepositCapKRW: guaranteeDepositCapKRW
      }, extra);
    }

    var scenarios = [];

    /* 1) 전세 — 정책 대출로 조달 */
    scenarios.push(evaluateScenario(common({
      id: 'jeonse_loan', label: jeonseLabel, type: 'jeonse',
      depositKRW: jeonseMedian, monthlyRentKRW: 0,
      loanAmountKRW: sizeLoan(jeonseMedian, assets, jeonseCap), loanRatePct: jeonseRate
    })));

    /* 2) 반전세 — 보증금 절반 + 나머지를 월세로 환산 */
    var semiDeposit = floorTo(jeonseMedian * K('tco.semi_jeonse_deposit_share'), depositRoundingUnit);
    var semiRent = floorTo((jeonseMedian - semiDeposit) * conversion / 100 / 12, monthlyRoundingUnit);
    scenarios.push(evaluateScenario(common({
      id: 'semi_jeonse', label: '반전세(보증부월세) — 보증금 절반 + 월세', type: 'monthly',
      depositKRW: semiDeposit, monthlyRentKRW: semiRent,
      loanAmountKRW: sizeLoan(semiDeposit, assets, jeonseCap), loanRatePct: jeonseRate
    })));

    /* 3) 월세 — 지역 표준 보증금 */
    scenarios.push(evaluateScenario(common({
      id: 'monthly_standard', label: '월세 — 지역 표준 보증금' + monthlyLabelSuffix, type: 'monthly',
      depositKRW: stdDeposit, monthlyRentKRW: stdRent,
      loanAmountKRW: sizeLoan(stdDeposit, assets, monthlyCap), loanRatePct: monthlyRate
    })));

    /* 4) 월세 — 저보증금·고월세형 */
    var lowDeposit = Math.min(K('tco.low_deposit_scenario_deposit_krw'), stdDeposit);
    var lowRent = stdRent + floorTo((stdDeposit - lowDeposit) * conversion / 100 / 12, monthlyRoundingUnit);
    scenarios.push(evaluateScenario(common({
      id: 'monthly_low_deposit', label: '월세 — 저보증금·고월세형', type: 'monthly',
      depositKRW: lowDeposit, monthlyRentKRW: lowRent,
      loanAmountKRW: 0, loanRatePct: 0.0
    })));

    stableSort(scenarios, function (a, b) {
      if (a.fitScore !== b.fitScore) return b.fitScore - a.fitScore;
      return a.monthlyEquivalentCostKRW - b.monthlyEquivalentCostKRW;
    });

    var best = scenarios[0];
    var cheapest = minBy(scenarios, function (s) { return s.tco5yKRW; });
    var rationale = [
      (region.name || '선택 지역') + ' 기준으로 전세·반전세·월세 ' +
      scenarios.length + '개 시나리오를 ' + horizonYears + '년 총비용(TCO)과 현재가치(NPV)로 비교했습니다.',
      "적합도 1위는 '" + best.label + "'(적합도 " + best.fitScore + '점, 월 환산 ' +
      money(best.monthlyEquivalentCostKRW) + ')입니다.',
      "5년 총비용이 가장 낮은 대안은 '" + cheapest.label + "'(" + money(cheapest.tco5yKRW) + ')입니다.'
    ];
    if (best.id !== cheapest.id) {
      rationale.push(
        '총비용이 가장 낮은 대안과 적합도 1위가 다릅니다. 자기자본 조달 여력과 ' +
        '월 현금흐름 중 무엇을 우선할지에 따라 선택이 달라집니다.'
      );
    }
    if (preferredType !== 'any') {
      rationale.push("선호 유형으로 '" + (preferredType === 'jeonse' ? '전세' : '월세') +
                     "'을 선택하셔서 적합도 점수에 가점을 반영했습니다.");
    }
    rationale.push(
      '보증금 자체는 비용에서 제외하고, 묶이는 자기자본의 기회비용(연 ' +
      pct(opportunityRatePct, 1) + ')만 반영했습니다.'
    );
    rationale.push(DISCLAIMER);

    return { scenarios: scenarios, rationale: rationale };
  }

  /* ══════════════════════════════════════════════════════════
     6. E4 — 보증금 리스크 (engines/risk.py)
     ══════════════════════════════════════════════════════════ */
  var IMPACTS = ['low', 'medium', 'high'];

  function jeonseRatioFactor(jeonseRatioPct) {
    var t1 = K('risk.jeonse_ratio_threshold_1');
    var t2 = K('risk.jeonse_ratio_threshold_2');
    var t3 = K('risk.jeonse_ratio_threshold_3');
    var t4 = K('risk.jeonse_ratio_threshold_4');
    var r = Number(jeonseRatioPct || 0);
    if (r <= 0) return [0, 'low', '전세가율 정보가 없어 위험 가중치를 적용하지 않았습니다.'];
    if (r < t1) return [K('risk.jeonse_ratio_weight_1'), 'low', '매매가 대비 전세가율이 낮아 보증금 회수 여력이 충분한 편입니다.'];
    if (r < t2) return [K('risk.jeonse_ratio_weight_2'), 'low', '전세가율이 안정 구간이지만 시세 하락에는 주의가 필요합니다.'];
    if (r < t3) return [K('risk.jeonse_ratio_weight_3'), 'medium', '전세가율이 ' + t2 + '%를 넘어 시세가 하락하면 보증금 일부가 위험해질 수 있습니다.'];
    if (r < t4) return [K('risk.jeonse_ratio_weight_4'), 'high', '전세가율이 ' + t3 + '%를 넘는 고위험 구간입니다. 선순위 채권 확인이 필수입니다.'];
    return [K('risk.jeonse_ratio_weight_5'), 'high', '전세가율이 ' + t4 + '% 이상으로 이른바 깡통전세 위험이 매우 큽니다.'];
  }

  function loanShareFactor(loanSharePct) {
    var t3 = K('risk.loan_share_threshold_3');
    var s = Number(loanSharePct || 0);
    if (s < K('risk.loan_share_threshold_1')) return [0, 'low', '보증금 대부분을 자기자본으로 조달해 대출 상환 부담이 낮습니다.'];
    if (s < K('risk.loan_share_threshold_2')) return [K('risk.loan_share_weight_2'), 'medium', '보증금의 일부를 대출로 조달합니다. 금리 변동에 유의하세요.'];
    if (s < t3) return [K('risk.loan_share_weight_3'), 'medium', '보증금의 절반 이상이 대출입니다. 보증금 미반환 시 상환 부담이 큽니다.'];
    return [K('risk.loan_share_weight_4'), 'high', '보증금의 ' + t3 + '% 이상이 대출로, 보증금 사고 시 부채만 남을 위험이 있습니다.'];
  }

  function depositSizeFactor(depositKRW, guaranteeDepositCapKRW) {
    var deposit = safeInt(depositKRW);
    var share = ratio(deposit, safeInt(guaranteeDepositCapKRW)) * 100;
    if (share < K('risk.deposit_size_threshold_1')) {
      return [0, 'low', '보증금 규모가 가입 가능 상한 대비 여유가 있어 보증 가입이 수월합니다.', share];
    }
    if (share < K('risk.deposit_size_threshold_2')) {
      return [K('risk.deposit_size_weight_2'), 'medium',
        '보증금이 가입 가능 상한의 절반을 넘어 물건별 보증한도(주택가격 x 90% - 선순위채권)를 ' +
        '미리 확인해야 합니다.', share];
    }
    return [K('risk.deposit_size_weight_3'), 'high', '보증금이 가입 가능 상한에 근접해 보증 가입이 거절될 수 있습니다.', share];
  }

  function marketFactor(marketRisk) {
    var key = String(marketRisk || 'medium').toLowerCase();
    var table = {
      low: [0, 'low', '해당 지역 임대차 시장은 수요가 안정적인 편입니다.', K('risk.market_value_pct_low')],
      medium: [K('risk.market_weight_medium'), 'medium', '해당 지역은 거래량·시세 변동을 주기적으로 확인할 필요가 있습니다.', K('risk.market_value_pct_medium')],
      high: [K('risk.market_weight_high'), 'high', '해당 지역은 시세 하락·거래 위축 위험이 상대적으로 큽니다.', K('risk.market_value_pct_high')]
    };
    return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : table.medium;
  }

  function exposureMultiplier(depositKRW) {
    var deposit = safeInt(depositKRW);
    if (deposit >= K('risk.low_exposure_krw')) return 1.0;
    if (deposit >= K('risk.minimal_exposure_krw')) return K('risk.exposure_multiplier_low');
    return K('risk.exposure_multiplier_minimal');
  }

  /** 파이썬 `risk.scan_deposit_risk`. */
  function scanDepositRisk(args) {
    var bandLowMax = K('risk.band_low_max');
    var bandMediumMax = K('risk.band_medium_max');
    var minimalExposureKRW = K('risk.minimal_exposure_krw');

    var deposit = safeInt(args.depositKRW);
    var loan = Math.min(safeInt(args.loanAmountKRW), deposit);
    var loanShare = ratio(loan, deposit) * 100;
    var exposure = exposureMultiplier(deposit);

    var factors = [];
    var score = 0.0;

    var jr = jeonseRatioFactor(args.jeonseRatioPct);
    score += jr[0] * exposure;
    factors.push({
      name: '전세가율',
      valuePct: roundHalf(Number(args.jeonseRatioPct || 0), 1),
      impact: exposure >= 1.0 ? jr[1] : 'low',
      note: jr[2]
    });

    var guaranteeCap = safeInt(args.guaranteeDepositCapKRW);
    var overCap = deposit > guaranteeCap;
    var gWeight, gImpact, gNote;
    if (args.guaranteeAvailable && !overCap) {
      gWeight = 0; gImpact = 'low';
      gNote = '전세보증금반환보증 가입이 가능한 지역·물건 조건입니다. 가입을 강력히 권장합니다.';
    } else if (overCap) {
      gWeight = K('risk.guarantee_unavailable_weight'); gImpact = 'high';
      gNote = '보증금이 가입 가능한 전세보증금 상한 ' + money(args.guaranteeDepositCapKRW) +
              '을 넘어 반환보증에 가입할 수 없습니다. 보증금 미반환 시 회수 수단이 제한됩니다.';
    } else {
      gWeight = K('risk.guarantee_unavailable_weight'); gImpact = 'high';
      gNote = '보증보험 가입이 어려운 조건입니다. 보증금 미반환 시 회수 수단이 제한됩니다.';
    }
    score += gWeight * (deposit >= minimalExposureKRW ? 1.0 : K('risk.guarantee_small_deposit_multiplier'));
    factors.push({
      name: '보증보험 가입 가능성',
      valuePct: (args.guaranteeAvailable && !overCap) ? 100.0 : 0.0,
      impact: gImpact,
      note: gNote
    });

    var ls = loanShareFactor(loanShare);
    score += ls[0] * exposure;
    factors.push({
      name: '보증금 내 대출 비중',
      valuePct: roundHalf(loanShare, 1),
      impact: exposure >= 1.0 ? ls[1] : 'low',
      note: ls[2]
    });

    var ds = depositSizeFactor(deposit, args.guaranteeDepositCapKRW);
    score += ds[0];
    factors.push({
      name: '보증금 규모 (가입 가능 상한 대비)',
      valuePct: roundHalf(ds[3], 1),
      impact: ds[1],
      note: ds[2]
    });

    var mf = marketFactor(args.marketRisk);
    score += mf[0];
    factors.push({ name: '지역 임대차 시장 여건', valuePct: mf[3], impact: mf[1], note: mf[2] });

    var total = Math.trunc(Math.max(0, Math.min(100, roundHalf(score, 0))));
    var band;
    if (total <= bandLowMax) band = 'low';
    else if (total <= bandMediumMax) band = 'medium';
    else band = 'high';

    var where = args.regionName || '선택 지역';
    var rationale = [
      where + ' 기준 보증금 ' + money(deposit) + '에 대한 위험 점수는 100점 만점에 ' +
      total + '점(' + band + ')입니다.'
    ];
    if (deposit <= 0) {
      rationale.push('보증금이 없어 보증금 미반환 위험은 사실상 없습니다.');
    } else {
      if (exposure < 1.0) {
        rationale.push(
          '보증금이 ' + money(deposit) + '으로 소액이어서 전세가율·대출비중 가중치를 ' +
          pct(exposure * 100, 0) + ' 수준으로 완화 적용했습니다.'
        );
      }
      var ordered = factors.slice();
      stableSort(ordered, function (a, b) { return IMPACTS.indexOf(b.impact) - IMPACTS.indexOf(a.impact); });
      rationale.push("가장 큰 위험 요인은 '" + ordered[0].name + "'입니다: " + ordered[0].note);
    }

    rationale.push({
      low: '계약 전 등기부등본 확인과 확정일자·전입신고만 지키면 관리 가능한 수준입니다.',
      medium: '선순위 채권과 임대인 세금 체납 여부를 반드시 확인하고 보증보험에 가입하세요.',
      high: '현재 조건으로는 계약을 재검토하거나 보증금을 낮춘 대안을 우선 검토하세요.'
    }[band]);
    rationale.push(
      '위험 점수는 공개된 일반 지표를 단순화한 프로토타입 산식이며, 실제 계약 심사 결과와 ' +
      '다를 수 있습니다.'
    );

    return { score: total, band: band, factors: factors, rationale: rationale };
  }

  /* ══════════════════════════════════════════════════════════
     7. 조립 (engines/__init__.py)
     ══════════════════════════════════════════════════════════ */

  /** 파이썬 `engines.guarantee_deposit_cap_for` (F-4). */
  function guaranteeDepositCapFor(region) {
    var prefixes = K('risk.metro_sido_code_prefixes');
    var code = String(region.code || '');
    var metro = prefixes.some(function (p) { return code.indexOf(p) === 0; });
    return metro ? K('risk.guarantee_deposit_cap_metro_krw') : K('risk.guarantee_deposit_cap_other_krw');
  }

  /** 파이썬 `engines._loan_option`. */
  function loanOption(evaluated, priority, depositKRW, assetsKRW) {
    var usable = {};
    evaluated.forEach(function (p) {
      if (p.status === 'eligible' || p.status === 'conditional') usable[p.id] = p;
    });
    var gap = Math.max(0, safeInt(depositKRW) - safeInt(assetsKRW));

    var best = null;
    priority.forEach(function (policyId) {
      var policy = usable[policyId];
      if (!policy) return;
      var rateRange = policy.rateRangePct && policy.rateRangePct.length ? policy.rateRangePct : [0.0, 0.0];
      var rate = Number(rateRange[rateRange.length - 1]);
      var coverage = gap ? Math.min(gap, policy.maxAmountKRW) : policy.maxAmountKRW;
      /* 파이썬의 `candidate[:2] > best[:2]` — (coverage, -rate) 사전식 비교 */
      if (best === null || coverage > best.coverage ||
          (coverage === best.coverage && -rate > -best.rate)) {
        best = { coverage: coverage, rate: rate, policy: policy };
      }
    });

    if (best === null) return null;
    return { name: best.policy.name, maxAmountKRW: best.policy.maxAmountKRW, ratePct: best.rate };
  }

  /** 파이썬 `engines._verdict_caveat`. */
  function verdictCaveat(best, recommended, affordability, scenarios) {
    if (best.verdict === 'affordable') return '';

    var monthly = safeInt(best.monthlyEquivalentCostKRW);
    var over = monthly - safeInt(recommended);
    var maxCost = safeInt(affordability.maxMonthlyHousingCostKRW);

    var note;
    if (best.verdict === 'stretch') {
      note = ' 다만 이 안은 권장 상한 ' + money(recommended) + '을 ' + money(over) + ' 초과하는' +
             ' 다소 무리한 선택(stretch)으로, 감당 가능 상한 ' + money(maxCost) + ' 이내이긴 하나' +
             ' 저축 여력이 줄어드는 점을 감안하셔야 합니다.';
    } else {
      note = ' 다만 이 안은 감당 가능 상한 ' + money(maxCost) + '을 초과해' +
             ' 현재 소득 기준으로는 권장하지 않습니다(unaffordable).';
    }

    var within = scenarios.filter(function (s) { return s.verdict === 'affordable'; });
    if (within.length) {
      var alt = minBy(within, function (s) { return s.monthlyEquivalentCostKRW; });
      note += " 권장 상한 이내 대안으로는 '" + alt.label + "'(월 환산 " +
              money(alt.monthlyEquivalentCostKRW) + ')이 있습니다.';
    } else {
      note += ' 비교한 대안 중 권장 상한을 만족하는 안이 없어, 보증금을 낮추거나' +
              ' 인근의 시세가 낮은 지역을 함께 검토하시길 권합니다.';
    }
    return note;
  }

  /** 파이썬 `engines._build_summary`. */
  function buildSummary(region, affordability, scenarios, policies, risk) {
    var regionName = region.name || '선택 지역';
    var recommended = affordability.recommendedMonthlyHousingCostKRW;
    var eligible = policies.filter(function (p) { return p.status === 'eligible'; });
    var conditional = policies.filter(function (p) { return p.status === 'conditional'; });

    var head = recommended <= 0
      ? regionName + ' 기준, 현재 소득·부채 구조로는 감당 가능한 주거비를 산출할 수 없습니다.'
      : regionName + ' 기준, 월 ' + money(recommended) + ' 이내 주거비가 권장됩니다.';

    var body = '';
    if (scenarios.length) {
      var best = scenarios[0];
      body = ' 비교한 ' + scenarios.length + "개 대안 중 '" + best.label + "'이(가) 적합도 " +
             best.fitScore + '점으로 가장 잘 맞으며, 5년 총비용 ' + money(best.tco5yKRW) + ', ' +
             '월 환산 ' + money(best.monthlyEquivalentCostKRW) + '입니다.';
      body += verdictCaveat(best, recommended, affordability, scenarios);
    }

    var policyPart;
    if (eligible.length) {
      policyPart = ' 지금 바로 신청 가능한 제도는 ' +
        eligible.slice(0, 2).map(function (p) { return p.name; }).join(', ') +
        ' 등 ' + eligible.length + '건입니다.';
    } else if (conditional.length) {
      policyPart = ' 추가 서류 확인이 필요한 조건부 제도가 ' + conditional.length + '건 있습니다.';
    } else {
      policyPart = ' 현재 프로필에 바로 맞는 지원 제도는 확인되지 않았습니다.';
    }

    var riskLabel = { low: '낮음', medium: '보통', high: '높음' }[risk.band];
    return head + body + policyPart + ' 보증금 위험도는 ' + risk.score + '점(' + riskLabel + ')입니다.';
  }

  /** 파이썬 `engines._utc_stamp` — `%Y-%m-%dT%H:%M:%SZ`. */
  function utcStamp(nowMs) {
    return new Date(nowMs).toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  /**
   * 파이썬 `engines.analyze`.
   *
   * `now` 를 **주입받는다** (SPEC 5.3). 기본값을 두면 그 기본값이 곧 시계 읽기이고,
   * 그러면 결정성 테스트가 성립하지 않는다. 활성 규칙 질의에 쓴 것과 **같은 순간 하나**다.
   */
  function analyze(profile, options) {
    if (!options || options.now == null) {
      throw new Error('analyze(profile, {now}) — 시각을 주입해야 합니다 (SPEC 5.3).');
    }
    var nowMs = options.now;
    var records = regionRecords();
    var regions = records.map(function (r) { return r.payload; });
    var policies = activePolicies(nowMs);

    var regionCode = String(profile.regionCode || '');
    var region;
    if (regionCode) {
      region = findRegion(regionCode, regions);
      if (region === null) throw new Error('알 수 없는 지역 코드입니다: ' + regionCode);
    } else {
      region = regions[0];
    }

    var preferredType = profile.preferredType || 'any';
    if (['jeonse', 'monthly', 'any'].indexOf(preferredType) === -1) preferredType = 'any';

    var affordability = assessAffordability(profile);
    var eligibility = evaluatePolicies(profile, policies, region.name || '');
    var evaluated = eligibility.policies;
    var guaranteeDepositCap = guaranteeDepositCapFor(region);

    var tco = buildScenarios(
      region, profile, affordability,
      loanOption(evaluated, K('engines.jeonse_loan_priority'), region.jeonseMedianKRW || 0, profile.liquidAssetsKRW || 0),
      loanOption(evaluated, K('engines.monthly_loan_priority'), region.monthlyDepositKRW || 0, profile.liquidAssetsKRW || 0),
      preferredType, guaranteeDepositCap
    );
    var scenarios = tco.scenarios;

    var top = scenarios.length ? scenarios[0] : { depositKRW: 0, loanAmountKRW: 0 };
    var risk = scanDepositRisk({
      depositKRW: top.depositKRW || 0,
      jeonseRatioPct: region.jeonseRatioPct || 0,
      loanAmountKRW: top.loanAmountKRW || 0,
      guaranteeAvailable: region.guaranteeAvailable === undefined ? true : Boolean(region.guaranteeAvailable),
      marketRisk: region.marketRisk || 'medium',
      regionName: region.name || '',
      guaranteeDepositCapKRW: guaranteeDepositCap
    });

    var response = {
      affordability: affordability,
      scenarios: scenarios,
      policies: evaluated,
      risk: risk,
      summary: buildSummary(region, affordability, scenarios, evaluated, risk),
      meta: {
        generatedAt: utcStamp(nowMs),
        engineVersion: requireArtifact('HOME_COMPASS_MODEL_CONSTANTS').$generated.engineVersion,
        region: { code: region.code || '', name: region.name || '' },
        disclaimer: DISCLAIMER
      }
    };

    /* SPEC 2.4 · D-13 — 생성물의 계보로 등급과 사유를 산정한다 (아래 8절).
       판정에 **실제로 쓰인** 지역 레코드를 다시 고르지 않고 `meta.region.code` 로 찾는다
       — 엔진의 선택 규칙을 여기서 다시 쓰면 두 구현이 갈린다 (`main.build_internal` 과 같은 규율). */
    var lineage = buildLineage(findRegionRecord(records, response.meta.region.code),
                               activeRuleVersions(nowMs), evaluated);
    response.provenance = lineage.provenance;
    response.dataGrade = lineage.dataGrade;
    return response;
  }

  function findRegionRecord(records, code) {
    for (var i = 0; i < records.length; i++) if (records[i].code === code) return records[i];
    return null;
  }

  /* ══════════════════════════════════════════════════════════
     8. dataGrade · provenance (SPEC 2.4 · D-13) — **로컬 경로 전용**

     백엔드 응답의 등급은 백엔드가 만든다 (코디네이터 결정 2026-08-15). 여기서
     산정하는 것은 **로컬 판정 경로가 쓴 사실**의 계보뿐이며, 그 사실은 전부 생성물이라
     계보가 완전하다.

     SPEC 2.4 를 문자 그대로 적용한다.
       · 산정 대상 — 이 판정에 실제로 쓰인 사실 중 `verification != our_choice`.
         규범적 선택은 신선도 개념이 없어 등급에 들어가지 않으나 `provenance` 에는 실린다.
       · 우선순위 — 가장 나쁜 등급이 이긴다 (C > B > A).
       · 사유 — 원인 유형(`stale` · `unverified` · `pending_review`)을 구분해 담고
         각 사유가 `provenance` 항목을 가리킨다.

     `pending_review` 는 승인 대기 큐에서 오고 그것은 5단계 산출물이다. 지금은 그
     사유가 **나올 수 없다** — 구조만 두고 없는 것을 있는 척 그리지 않는다.

     ★ **`stale` 은 판정하지 않는다. 그리고 그 사실을 응답에 드러낸다** (D-13 과업).
       SPEC 2.4 가 「신선도 임계는 미정이며 값을 감으로 정해 코드에 박는 것을 금지한다」고
       못박았고 그 값은 아직 없다. 없는 판정을 조용히 넘기면 화면은 그것을 「신선하다」로
       읽는다 — 그것이 D-11 이 금지한 침묵 폴백이다.

     ★ 여기는 `backend/src/home_compass/main.py` 의 `build_lineage` · `grade_facts` 와
       **같은 규칙**이다. 두 경로가 SPEC 2.4 를 각자 읽으면 반드시 어긋나고, 그것이
       계약 결정 #37 이 지목한 지배적 실패 양상이다. 같음을 붙드는 것은 주장이 아니라
       `backend/tests/test_frontend_local_engine_equivalence.py` 다 — 그 파수병이
       `dataGrade` · `provenance` 를 백엔드 결과와 대조한다.
       **이 절을 고치면 그 파이썬 쪽도 같은 PR 에서 고쳐야 한다.**
     ══════════════════════════════════════════════════════════ */

  /* 어느 사실이 응답의 어느 숫자를 근거짓는가 (RFC 6901). 사실이 실제로 흘러드는
     응답 위치를 가리킨다 — 좁게 특정할 수 없는 곳은 그 부분트리를 가리키고,
     특정할 수 있는 곳(정책 하나)은 그 인덱스까지 가리킨다. */
  var ENGINE_TARGETS = {
    affordability: ['/affordability'],
    tco: ['/scenarios'],
    risk: ['/risk'],
    eligibility: ['/policies'],
    engines: ['/scenarios']
  };

  /* 신선도 임계로 보이는 상수 키를 알아보는 표지. **값을 여기 적지 않는다** — 여기 있는
     것은 [임계가 등재되었는가]를 생성물에서 읽는 방법뿐이다 (파이썬
     `main.FRESHNESS_THRESHOLD_KEY_MARKERS` 와 같은 목록이다). */
  var FRESHNESS_THRESHOLD_KEY_MARKERS = ['freshness', 'stale'];

  /** 등재된 신선도 임계 상수의 키. **지금은 0건이다** (SPEC 2.4 · Part 0-E #4).
   *
   * 0건이면 `stale` 여부를 판정할 수 없고 그 사실이 `freshness_not_evaluated` 사유로
   * 실린다. 임계가 등재되는 날 이 목록이 비지 않게 되어 표기가 **자동으로** 꺼진다 —
   * 어딘가의 `false` 리터럴을 사람이 찾아 지우는 구조로 두지 않는다.
   */
  function freshnessThresholdKeys(entries) {
    return Object.keys(entries).filter(function (key) {
      var lowered = key.toLowerCase();
      return FRESHNESS_THRESHOLD_KEY_MARKERS.some(function (marker) {
        return lowered.indexOf(marker) !== -1;
      });
    }).sort();
  }

  function buildLineage(regionRecord, ruleVersions, evaluatedPolicies) {
    var items = [];

    /* (1) 지역 시세 — 사실 단위(필드별) 계보. 레코드 요약으로 접지 않는다. */
    if (regionRecord) {
      var factFields = requireArtifact('HOME_COMPASS_REGIONS').$factFields;
      factFields.forEach(function (field) {
        var prov = regionRecord.fieldProvenance[field];
        items.push({
          fact: '지역 시세 · ' + field + ' (' + regionRecord.name + ')',
          factKind: 'region_field',
          provenance: prov,
          targets: ['/scenarios', '/risk']
        });
      });
    }

    /* (2) 판정에 참여한 승인 규칙 — 정책별로 `/policies/{i}` 를 가리킨다. */
    ruleVersions.forEach(function (version) {
      var index = -1;
      for (var i = 0; i < evaluatedPolicies.length; i++) {
        if (evaluatedPolicies[i].id === version.policyId) { index = i; break; }
      }
      items.push({
        fact: '정책 규칙 · ' + (version.payload.name || version.policyId) +
              ' (' + version.ruleVersion.id + ')',
        factKind: 'rule_version',
        provenance: version.provenance,
        targets: index >= 0 ? ['/policies/' + index] : ['/policies']
      });
    });

    /* (3) 모델 상수 — 엔진이 실제로 조회한 키만. */
    var entries = requireArtifact('HOME_COMPASS_MODEL_CONSTANTS').entries;
    Object.keys(entries).sort().forEach(function (key) {
      var engine = key.split('.')[0];
      if (!Object.prototype.hasOwnProperty.call(ENGINE_TARGETS, engine)) return;
      items.push({
        fact: '모델 상수 · ' + key,
        factKind: 'model_constant',
        provenance: entries[key].provenance,
        targets: ENGINE_TARGETS[engine]
      });
    });

    /* --- 등급 산정 (2.4) --- */
    var reasons = [];
    items.forEach(function (item, index) {
      var verification = item.provenance.verification;
      if (verification === 'our_choice') return;      /* 규범적 선택은 등급에 들어가지 않는다 */
      if (verification === 'unverified' || verification === 'stale') {
        reasons.push({
          type: verification,
          provenanceIndex: index,
          fact: item.fact,
          message: verification === 'unverified'
            ? item.fact + ' 의 출처를 확인하지 못했습니다.'
            : item.fact + ' 의 관측 시점이 신선도 기준을 넘었습니다.'
        });
      }
    });

    /* ★ 신선도는 **판정하지 않았다.** 그 사실을 조용히 넘기지 않는다 (SPEC 2.4).
       특정 사실의 결함이 아니라 판정 자체가 서지 않은 상태이므로 `provenanceIndex` 는
       `null` 이다 — 한 항목을 가리키면 「그 사실만 문제」로 읽힌다. */
    var freshnessEvaluated = freshnessThresholdKeys(entries).length > 0;
    if (!freshnessEvaluated) {
      reasons.push({
        type: 'freshness_not_evaluated',
        provenanceIndex: null,
        fact: null,
        message: '신선도 임계가 아직 정해지지 않아 stale 여부를 판정하지 않았습니다. ' +
                 '이 등급은 검증 상태만으로 산정된 것이며, 신선도가 확인되었다는 뜻이 아닙니다 ' +
                 '(SPEC 2.4).'
      });
    }

    /* 가장 나쁜 것이 이긴다 (`C` > `B` > `A`). `A` 는 「전부 verified **이며** 신선도
       기준 이내」라는 두 조건의 곱이므로, 뒤 절을 판정하지 못했으면 `A` 를 낼 수 없다.
       **`null` 은 「깨끗함」이 아니라 「산정할 수 없음」이다.** */
    var grade;
    if (reasons.some(function (r) { return r.type === 'unverified'; })) grade = 'C';
    else if (reasons.some(function (r) { return r.type === 'stale' || r.type === 'pending_review'; })) grade = 'B';
    else if (!freshnessEvaluated) grade = null;
    else grade = 'A';

    return {
      provenance: items,
      dataGrade: { grade: grade, reasons: reasons }
    };
  }

  /* ══════════════════════════════════════════════════════════
     9. 정렬 보조 — 파이썬의 안정 정렬·min 규약을 그대로 옮긴다
     ══════════════════════════════════════════════════════════ */

  /** `Array.prototype.sort` 는 ES2019 부터 안정 정렬이지만, 그 사실에 기대지 않는다. */
  function stableSort(list, compare) {
    var decorated = list.map(function (item, index) { return { item: item, index: index }; });
    decorated.sort(function (a, b) {
      var r = compare(a.item, b.item);
      return r !== 0 ? r : a.index - b.index;
    });
    for (var i = 0; i < list.length; i++) list[i] = decorated[i].item;
    return list;
  }

  /** 파이썬 `min(iterable, key=...)` — 동점이면 **먼저 나온 것**이 이긴다. */
  function minBy(list, key) {
    var best = list[0];
    var bestKey = key(best);
    for (var i = 1; i < list.length; i++) {
      var k = key(list[i]);
      if (k < bestKey) { best = list[i]; bestKey = k; }
    }
    return best;
  }

  global.HomeCompassLocalEngine = {
    status: status,
    analyze: analyze,
    regions: regionRecords,
    activeRuleVersions: activeRuleVersions,
    activePolicies: activePolicies,
    constant: K,
    constantProvenance: constantProvenance,
    DISCLAIMER: DISCLAIMER,
    /* 파수병이 조각별로 확인할 수 있도록 노출한다 — 화면은 `analyze` 만 쓴다. */
    _engines: {
      assessAffordability: assessAffordability,
      evaluatePolicies: evaluatePolicies,
      buildScenarios: buildScenarios,
      scanDepositRisk: scanDepositRisk,
      guaranteeDepositCapFor: guaranteeDepositCapFor
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
