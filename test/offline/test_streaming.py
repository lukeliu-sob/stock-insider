"""Streaming output tests (TP-007a, FR-019).

S1 semantics: the first streamed delta reaches the sink strictly
before the completion marker; deltas arrive in order; tool phases do
not swallow deltas; the provider sets stream flags and passes tool
specs through.
"""

from types import SimpleNamespace

from stockinsider.agent.providers import ChatOutcome, OpenAICompatibleProvider, ProviderConfig


class ScriptedProvider:
    """Offline scripted provider for streaming tests."""

    def __init__(self, outcomes: list[ChatOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.seen_messages: list[list[dict]] = []
        self.seen_tools: list | None = None

    def complete(self, messages, *, tools=None, stream_sink=None):
        """Implements: REQ-SI-FR-019 (ADR-001)."""
        self.seen_messages.append(list(messages))
        self.seen_tools = tools
        outcome = self._outcomes.pop(0)
        if stream_sink is not None and outcome.text and not outcome.tool_calls:
            for piece in outcome.text.split(" "):
                stream_sink(piece + " ")
            stream_sink("\n")
        return outcome


def _sink_recorder() -> tuple[list[str], callable]:
    seen: list[str] = []

    def sink(piece: str) -> None:
        seen.append(piece)

    return seen, sink


def test_first_delta_arrives_before_completion() -> None:
    seen, sink = _sink_recorder()
    provider = ScriptedProvider([ChatOutcome(text="hello streaming world", usage={})])
    outcome = provider.complete([{"role": "user", "content": "x"}], stream_sink=sink)
    assert outcome.text == "hello streaming world"
    assert seen[0] == "hello "  # first delta observed during the call
    assert seen[-1] == "\n"  # completion marker last


def test_deltas_arrive_in_order() -> None:
    seen, sink = _sink_recorder()
    provider = ScriptedProvider([ChatOutcome(text="a b c", usage={})])
    provider.complete([{"role": "user", "content": "x"}], stream_sink=sink)
    assert seen == ["a ", "b ", "c ", "\n"]


def test_tool_phase_then_streamed_text() -> None:
    seen, sink = _sink_recorder()
    provider = ScriptedProvider(
        [
            ChatOutcome(
                tool_calls=[{"id": "t1", "type": "function", "function": {"name": "budget.query", "arguments": "{}"}}],
                usage={},
            ),
            ChatOutcome(text="done streaming after tools", usage={}),
        ]
    )
    first = provider.complete([{"role": "user", "content": "x"}], stream_sink=sink)
    assert first.tool_calls and not seen  # no text deltas during tool phase
    second = provider.complete([{"role": "user", "content": "x"}], stream_sink=sink)
    assert second.text == "done streaming after tools"
    assert seen and seen[-1] == "\n"


def _streaming_fake_client(chunks):
    def factory(base_url: str, api_key):
        def create(**kwargs):
            if kwargs.get("stream"):
                return iter(chunks)
            raise AssertionError("non-stream path taken with a sink")

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    return factory


def _chunk(content=None, tool_call=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=[tool_call] if tool_call else None)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_real_provider_sets_stream_flag_and_aggregates() -> None:
    chunks = [
        _chunk(content="Hel"),
        _chunk(content="lo world"),
        _chunk(usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2)),
    ]
    config = ProviderConfig(
        chat_base_url="https://x.example/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    provider = OpenAICompatibleProvider(config, api_key="sk-x", client_factory=_streaming_fake_client(chunks))
    seen, sink = _sink_recorder()
    outcome = provider.complete([{"role": "user", "content": "hi"}], stream_sink=sink)
    assert outcome.text == "Hello world"
    assert seen == ["Hel", "lo world"]
    assert outcome.usage == {"prompt_tokens": 3, "completion_tokens": 2}


def test_real_provider_streams_tool_call_deltas() -> None:
    chunks = [
        _chunk(tool_call=SimpleNamespace(index=0, id="call-1", function=SimpleNamespace(name="b", arguments='{"a"'))),
        _chunk(tool_call=SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments=": 1}"))),
        _chunk(usage=SimpleNamespace(prompt_tokens=5, completion_tokens=1)),
    ]
    config = ProviderConfig(
        chat_base_url="https://x.example/v1",
        chat_model="m",
        embedding_base_url=None,
        embedding_model="m",
        budgets={},
    )
    provider = OpenAICompatibleProvider(config, api_key="sk-x", client_factory=_streaming_fake_client(chunks))
    _seen, sink = _sink_recorder()
    outcome = provider.complete(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "b"}}],
        stream_sink=sink,
    )
    assert outcome.tool_calls == [
        {"id": "call-1", "type": "function", "function": {"name": "b", "arguments": '{"a": 1}'}}
    ]
    assert outcome.text == ""
