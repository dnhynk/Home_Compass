@echo off
setlocal
title KB First-Home Compass - 시세 수집 배치

rem -------------------------------------------------------------------------
rem This file is saved in CP949 (Korean ANSI) with CRLF line endings and
rem deliberately does NOT call chcp 65001 - same constraint as dev.bat.
rem cmd.exe re-seeks the batch file by BYTE offset after every command; under
rem codepage 65001 those offsets desynchronise on multi-byte lines. CP949 is
rem the console default on Korean Windows, so the offsets stay in sync.
rem Keep this file CP949 + CRLF. Re-saving it as UTF-8 reintroduces the bug.
rem -------------------------------------------------------------------------

echo ============================================
echo  시세 수집 배치 (SPEC 3단계)
echo  국토교통부 아파트 실거래가 - 전월세 / 매매
echo ============================================
echo.

cd /d "%~dp0.."

rem SPEC 1.3 - 시연에서 배치를 눈앞에서 돌려야 하므로 별도 명령으로 실행 가능해야 한다.
rem 진입점의 정본은 firsthome.ingest.market 이며 이 배치는 그것을 부르기만 한다.
set PYTHONPATH=%CD%\backend\src
python -m firsthome.ingest.market %*
set RC=%ERRORLEVEL%

if %RC% neq 0 (
  echo.
  echo [!] 배치가 종료코드 %RC% 로 끝났습니다.
  echo     키가 없으면 수집은 정상적으로 실패하고 이전 값이 유지됩니다 - SPEC 9.2.1.
  echo     그 경우도 저장소는 훼손되지 않습니다.
)

endlocal & exit /b %RC%
