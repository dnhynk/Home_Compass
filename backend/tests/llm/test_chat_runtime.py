"""Live provider compatibility and public failure boundaries, without API calls."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import jsonschema
import pytest

from home_compass.llm import agent


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
INPUTS = dict(constants={}, regions=[], policies=[], now=NOW)


def test_luna_function_call_finishes_with_supported_request_options(monkeypatch):
    import openai

    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="analyze", arguments="{}"))
    turns = iter([
        SimpleNamespace(content=None, tool_calls=[call]),
        SimpleNamespace(content="도구 결과를 확인했습니다.", tool_calls=[]),
    ])

    def completion(**kwargs):
        # The live API rejects Luna function tools when reasoning is enabled.
        assert kwargs["reasoning_effort"] == "none"
        assert kwargs["model"] == "gpt-5.6-luna"
        assert kwargs["tools"]
        return SimpleNamespace(choices=[SimpleNamespace(message=next(turns))])

    create = Mock(side_effect=completion)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(agent, "execute_tool", lambda *args, **kwargs: ({"verified": True}, "검증 완료"))
    result = agent._openai_chat("주거비를 알려주세요", {}, [], **INPUTS)
    assert result["mode"] == "live"
    assert len(result["toolCalls"]) == 1
    assert create.call_count == 2
    assert create.call_args.kwargs["messages"][-1]["role"] == "tool"


def test_fallback_does_not_expose_provider_error_body(monkeypatch):
    secret = "synthetic-secret-do-not-publish"
    provider = Mock(side_effect=RuntimeError(f"API error with token {secret} and private payload"))
    monkeypatch.setattr(agent, "get_llm_mode", lambda: "openai")
    monkeypatch.setitem(agent._PROVIDER_HANDLERS, "openai", provider)
    monkeypatch.setattr(agent, "_offline_chat", lambda *args, **kwargs: {
        "reply": "검증된 엔진 결과", "mode": "offline", "provider": "offline", "toolCalls": []})
    result = agent.chat("주거비를 알려주세요", **INPUTS)
    assert result["mode"] == "offline"
    assert result["degradedFrom"] == "openai"
    assert secret not in str(result)
    assert "private payload" not in str(result)
    assert "검증된 엔진 결과" in result["reply"]
    assert provider.call_count == agent.LLM_MAX_ATTEMPTS


@pytest.mark.parametrize("extra", [
    {"model": "gpt-5.6-luna"},
    {"model": "gpt-5.6-luna", "retried": 1},
    {"degradedFrom": "openai", "degradedReason": "일시적인 연결 오류", "attempts": 2},
])
def test_chat_contract_accepts_live_and_degraded_metadata(extra):
    from home_compass.main import ChatResponse

    jsonschema.validate({"reply": "안내", "toolCalls": [], "mode": "live", "provider": "openai", **extra},
                        ChatResponse.model_json_schema())


@pytest.mark.parametrize("mode,extra,expected", [
    ("live", {"model": "gpt-5.6-luna"}, "success"),
    ("offline", {}, "success"),
    ("offline", {"degradedFrom": "openai"}, "failure"),
])
def test_status_metrics_distinguish_provider_failure_from_intentional_offline(monkeypatch, mode, extra, expected):
    from home_compass import main

    observed = Mock()
    monkeypatch.setattr(main, "log_llm_chat", observed)
    monkeypatch.setattr(main, "get_llm_mode", lambda: "openai" if extra else "offline")
    monkeypatch.setattr(main, "chat", lambda *args, **kwargs: {
        "reply": "안내", "toolCalls": [], "mode": mode, "provider": "openai" if mode == "live" else "offline", **extra})
    result = main.chat_endpoint(main.ChatRequest(message="안녕하세요"))
    assert result["mode"] == mode
    assert observed.call_args.kwargs["outcome"] == expected
