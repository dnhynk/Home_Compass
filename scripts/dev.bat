@echo off
setlocal
title Home_Compass

rem -------------------------------------------------------------------------
rem This file is saved in CP949 (Korean ANSI) with CRLF line endings and
rem deliberately does NOT call chcp 65001. cmd.exe re-seeks the batch file by
rem BYTE offset after every command; under codepage 65001 those offsets
rem desynchronise on multi-byte lines, which sliced the Korean echo lines
rem mid-character and made cmd try to execute the fragments. CP949 is the
rem console default on Korean Windows, so the offsets stay in sync.
rem Keep this file CP949 + CRLF. Re-saving it as UTF-8 reintroduces the bug.
rem -------------------------------------------------------------------------

echo ============================================
echo  Home_Compass
echo  청년 주거 금융 의사결정 에이전트
echo ============================================
echo.

cd /d "%~dp0.."

echo [1/4] 의존성을 설치합니다...
python -m pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo [!] 의존성 설치에 실패했습니다. Python 3.11 이상인지 확인하세요.
    pause
    exit /b 1
)

echo [2/4] 엔진 테스트를 실행합니다...
cd backend
python -m pytest -q
if errorlevel 1 (
    echo.
    echo [!] 테스트가 실패했습니다. 위 로그를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [3/4] 저장소를 준비합니다...
rem 기동은 모델 상수를 저장소에서 읽고 전수 존재를 검증한다 (SPEC 5.1.1 fail-closed).
rem 시드되지 않은 저장소로는 서버가 뜨지 않는다. 두 번 돌려도 결과는 같다.
python ..\scripts\seed_store.py
if errorlevel 1 (
    echo.
    echo [!] 저장소 시드에 실패했습니다. 위 로그를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [4/4] 서버를 기동합니다.
echo.
echo     브라우저에서 http://127.0.0.1:8000 을 여세요.
echo     API 문서: http://127.0.0.1:8000/docs
echo     종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo.
if "%OPENAI_API_KEY%%ANTHROPIC_API_KEY%"=="" (
    echo     [i] 환경변수에 LLM API 키가 없습니다.
    echo     [i] 리포지토리 루트에 .env 파일이 있으면 키를 자동으로 인식합니다.
    echo     [i] 키가 전혀 없으면 AI 상담은 offline 템플릿 모드로 동작하며,
    echo         지불능력 / 시나리오 / 정책 / 리스크 판정은 전부 정상 동작합니다.
    echo     [i] 실제 모드는 http://127.0.0.1:8000/api/health 의 llm 값으로 확인하세요.
    echo.
)

cd src
rem ★ 워커를 1개로 명시한다. 세션 원장이 api 프로세스 메모리에 있으므로(SPEC 2.2 에
rem   Session 엔티티가 없고 D-8 이 로컬 단일 호스트를 못박았다) 워커가 둘 이상이면
rem   로그인이 요청마다 다른 프로세스로 흩어져 조용히 깨진다. 기본값에 기대지 않는다.
python -m uvicorn firsthome.main:app --host 127.0.0.1 --port 8000 --workers 1

endlocal
