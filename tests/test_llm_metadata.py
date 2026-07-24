from __future__ import annotations

from types import SimpleNamespace

from novelforge.llm.deepseek_client import DeepSeekClient


class Completions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="request-1",
            model="deepseek-chat",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="result"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=8,
                total_tokens=20,
            ),
        )


def test_deepseek_uses_configured_defaults_and_preserves_usage_metadata() -> None:
    client = DeepSeekClient(
        api_key="test",
        temperature=0.35,
        max_tokens=777,
    )
    completions = Completions()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = client.chat_completion_result([{"role": "user", "content": "hello"}])

    assert result.content == "result"
    assert result.total_tokens == 20
    assert result.request_id == "request-1"
    assert completions.kwargs["temperature"] == 0.35
    assert completions.kwargs["max_tokens"] == 777
    assert client.call_history == [result]


def test_explicit_generation_parameters_override_client_defaults() -> None:
    client = DeepSeekClient(api_key="test", temperature=0.35, max_tokens=777)
    completions = Completions()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    client.chat_completion_result(
        [{"role": "user", "content": "hello"}],
        temperature=0.1,
        max_tokens=123,
    )

    assert completions.kwargs["temperature"] == 0.1
    assert completions.kwargs["max_tokens"] == 123
