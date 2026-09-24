"""Tool registry: the authority membrane (blueprint §4.1, §9.1).

The LLM never touches storage, network, or computation directly; every
access flows through registered tools with validated schemas, gated
effect classes, and provenance-stamped results. Handlers are injected
by the composition layer. Imports: shared, plus the data facade —
the single sanctioned agent-to-data channel (blueprint §5; ADR-005).

Implements: REQ-SI-INV-003, REQ-SI-INV-001, REQ-SI-SEC-002 (ADR-005)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from stockinsider.shared.tools import (
    JSON_SCHEMA_TYPES,
    EffectClass,
    SourceKind,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolWireError,
    validate_arguments,
    validate_result_payload,
)


def register_data_tools(registry: Registry, data_store: Any) -> None:
    """Register the data-facade tool set (the only agent-to-data channel).

    symbol.search resolves mentions and records verified candidates in
    the symbol map; watchlist.add/remove are write tools whose gate is
    the user_confirmed argument plus the verified-resolution record
    (INV-004 deterministic backstop behind the prompt-level flow).

    Implements: REQ-SI-FR-004, REQ-SI-INV-004 (ADR-005, ADR-003)
    """

    def _symbol_search(args: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = data_store.resolver.search(args["query"])
        out: list[dict[str, Any]] = []
        for cand in candidates:
            data_store.record(cand)
            out.append(cand.as_dict())
        return out

    def _watchlist_add(args: dict[str, Any]) -> dict[str, Any]:
        return data_store.watchlist.add_verified(
            args["canonical_symbol"], user_confirmed=args["user_confirmed"], via="agent-tool"
        )

    def _watchlist_remove(args: dict[str, Any]) -> dict[str, Any]:
        return data_store.watchlist.remove(args["canonical_symbol"])

    registry.register(
        ToolSpec(
            name="symbol.search",
            description=(
                "Resolve a security mention against the symbol map and the EODHD "
                "search API; returns verified candidates. Present candidates to "
                "the user before any watchlist add."
            ),
            arguments_spec={"query": "str"},
            result_spec="list",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        _symbol_search,
    )
    registry.register(
        ToolSpec(
            name="watchlist.list",
            description="List active watchlist symbols with names and exchanges.",
            arguments_spec={},
            result_spec="list",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        lambda args: data_store.watchlist.list(),
    )
    registry.register(
        ToolSpec(
            name="watchlist.add",
            description=(
                "Add a verified symbol to the watchlist. Requires a prior "
                "symbol.search whose candidate the user explicitly confirmed; "
                "pass user_confirmed=true only after that confirmation."
            ),
            arguments_spec={"canonical_symbol": "str", "user_confirmed": "bool"},
            result_spec="dict",
            effect_class=EffectClass.WRITE,
            source_kind=SourceKind.API,
        ),
        _watchlist_add,
    )
    registry.register(
        ToolSpec(
            name="watchlist.remove",
            description=(
                "Remove a symbol from the watchlist; requires user_confirmed=true "
                "after showing the user what will be removed."
            ),
            arguments_spec={"canonical_symbol": "str", "user_confirmed": "bool"},
            result_spec="dict",
            effect_class=EffectClass.WRITE,
            source_kind=SourceKind.API,
        ),
        _watchlist_remove,
    )


def register_sync_tools(registry: Registry, data_store: Any) -> None:
    """Register sync.run (WRITE, user-confirmed) and sync.status (READ).

    Typing the slash command is the confirmation the write gate needs;
    the CLI subcommand is the other authorized entry (blueprint §9.1).

    Implements: REQ-SI-FR-001, REQ-SI-FR-013 (ADR-005, ADR-002)
    """

    def _run(args: dict[str, Any]) -> dict[str, Any]:
        return data_store.run_sync()

    def _status(args: dict[str, Any]) -> dict[str, Any]:
        return data_store.sync_status()

    registry.register(
        ToolSpec(
            name="sync.run",
            description=(
                "Run one market-data sync (indices first, gap queue, "
                "incrementals) under the daily call budget. The report "
                "lists per-symbol outcomes and deferred items."
            ),
            arguments_spec={"user_confirmed": "bool"},
            result_spec="dict",
            effect_class=EffectClass.WRITE,
            source_kind=SourceKind.API,
        ),
        _run,
    )
    registry.register(
        ToolSpec(
            name="sync.status",
            description="Budget usage, pending gap queue, and tracked-symbol counts.",
            arguments_spec={},
            result_spec="dict",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        _status,
    )


def register_market_tools(registry: Registry, data_store: Any) -> None:
    """Register the read tools that expose real market numerics (TP-010).

    market.quote returns the latest stored bar; fundamentals.summary
    returns the latest quarter plus the FR-002 coverage ratio. These
    are the first real market numbers flowing through the membrane
    into INV-001 snapshots.

    Implements: REQ-SI-FR-005, REQ-SI-FR-002 (ADR-005, ADR-002)
    """

    def _quote(args: dict[str, Any]) -> dict[str, Any]:
        row = data_store.conn.execute(
            "SELECT date, open, high, low, close, adjusted_close, volume, currency "
            "FROM market_bars WHERE canonical_symbol = ? ORDER BY date DESC LIMIT 1",
            (args["symbol"],),
        ).fetchone()
        if row is None:
            raise KeyError(f"{args['symbol']}: no stored market data (sync first; INV-003)")
        return dict(row) | {"symbol": args["symbol"]}

    def _fundamentals(args: dict[str, Any]) -> dict[str, Any]:
        from stockinsider.data.ingest.fundamentals import coverage

        return coverage(data_store.conn, args["symbol"])

    registry.register(
        ToolSpec(
            name="market.quote",
            description=(
                "Latest stored EOD bar for a canonical symbol: date, OHLC, "
                "adjusted close, volume, currency. Deterministic; data date included."
            ),
            arguments_spec={"symbol": "str"},
            result_spec="dict",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        _quote,
    )
    def _indicators(args: dict[str, Any]) -> dict[str, Any]:
        import json as _json

        from stockinsider.data.compute.indicators import (
            annualized_volatility,
            gross_margin,
            max_drawdown,
            net_margin,
            roe,
            yoy_growth,
        )

        symbol = args["symbol"]
        price_row = data_store.conn.execute(
            "SELECT date, close FROM market_bars WHERE canonical_symbol = ?"
            " ORDER BY date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        bars = data_store.conn.execute(
            "SELECT date, close FROM market_bars WHERE canonical_symbol = ?"
            " ORDER BY date DESC LIMIT 260",
            (symbol,),
        ).fetchall()
        if price_row is None:
            raise KeyError(f"{symbol}: no stored market data (sync first; INV-003)")
        income_rows = data_store.conn.execute(
            "SELECT period_end, data FROM fundamentals WHERE canonical_symbol = ?"
            " AND statement_type = 'income' ORDER BY period_end",
            (symbol,),
        ).fetchall()
        balance_rows = data_store.conn.execute(
            "SELECT period_end, data FROM fundamentals WHERE canonical_symbol = ?"
            " AND statement_type = 'balance' ORDER BY period_end DESC LIMIT 1",
            (symbol,),
        ).fetchall()

        def _field(row: Any, key: str) -> float | None:
            try:
                value = _json.loads(row["data"]).get(key)
            except (ValueError, TypeError):
                return None
            return float(value) if isinstance(value, (int, float)) else None

        revenue_series = [
            (str(row["period_end"]), _field(row, "totalRevenue") or 0.0)
            for row in income_rows
            if _field(row, "totalRevenue") is not None
        ]
        latest_income = income_rows[-1] if income_rows else None
        latest_revenue = _field(latest_income, "totalRevenue") if latest_income else None
        latest_net_income = _field(latest_income, "netIncome") if latest_income else None
        latest_equity = (
            _field(balance_rows[0], "totalStockholdersEquity") if balance_rows else None
        )

        snapshot = {
            "symbol": symbol,
            "as_of": price_row["date"],
            "valuation": {
                "note": (
                    "share count is not captured by the fundamentals adapter; "
                    "per-share ratios unavailable until it is (INV-003)"
                )
            },
            "profitability": {
                "roe": roe(latest_net_income, latest_equity),
                "net_margin": net_margin(latest_net_income, latest_revenue),
                "gross_margin": gross_margin(None, latest_revenue),
            },
            "growth": {
                "revenue_yoy": yoy_growth(revenue_series),
                "earnings_yoy": {
                    "unavailable": "quarterly net-income series not assembled in this snapshot"
                },
            },
            "risk": {
                "volatility": annualized_volatility([dict(bar) for bar in bars]),
                "max_drawdown": max_drawdown([dict(bar) for bar in bars]),
            },
        }
        return snapshot

    registry.register(
        ToolSpec(
            name="market.indicators",
            description=(
                "Deterministic indicator snapshot for a symbol: profitability "
                "(ROE, margins), growth (revenue YoY) and risk (annualized "
                "volatility, max drawdown) with data windows; unavailable "
                "sections are explicit. The LLM interprets, never computes."
            ),
            arguments_spec={"symbol": "str"},
            result_spec="dict",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.COMPUTED,
        ),
        _indicators,
    )
    registry.register(
        ToolSpec(
            name="fundamentals.summary",
            description=(
                "Latest stored fundamentals for a symbol with the FR-002 coverage "
                "ratio and explicit gap list; empty when the feed has not been ingested."
            ),
            arguments_spec={"symbol": "str"},
            result_spec="dict",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        _fundamentals,
    )


def register_news_tools(
    registry: Registry,
    data_store: Any,
    embed_provider: "tuple[Any, str] | None" = None,
) -> None:
    """Register the retrieval tool (FR-007: the only citable news source).

    news.search embeds the query through the injected provider, runs
    KNN over the vector store, and sanitizes every headline on the
    egress into model context (SEC-002 layer one). Raw storage is
    never altered. When the embedding provider is not configured the
    tool is not registered (explicit absence, not a broken tool).

    Implements: REQ-SI-FR-007, REQ-SI-SEC-002 (ADR-005, ADR-004)
    """
    if embed_provider is None:
        return
    provider, model_id = embed_provider

    def _search(args: dict[str, Any]) -> dict[str, Any]:
        from stockinsider.shared.sanitize import sanitize_text

        query = str(args["query"])
        k = int(args.get("k") or 5)
        bucket = args.get("symbol") or None
        vectors = provider.embed([query])
        if not vectors:
            raise KeyError("embedding provider returned no vector (INV-003)")
        rows = data_store.news_knn(vectors[0], model_id, k=k, bucket=bucket)
        results = [
            {
                "news_id": row["news_id"],
                "title": sanitize_text(row["title_raw"]),
                "url": row["url"],
                "domain": row["domain"],
                "seendate": row["seendate"],
                "bucket": row["bucket"],
                "distance": round(row["distance"], 4),
            }
            for row in rows
        ]
        return {
            "query": sanitize_text(query),
            "model_id": model_id,
            "results": results,
            "note": "titles sanitized at egress (SEC-002 layer one); cite only these items (FR-007)",
        }

    registry.register(
        ToolSpec(
            name="news.search",
            description=(
                "Semantic search over the stored news corpus (top-k by "
                "embedding distance). Returns sanitized titles with source "
                "URL, domain, publication timestamp and bucket; optional "
                "symbol scopes the search to that bucket. The only citable "
                "news source (FR-007)."
            ),
            arguments_spec={"query": "str"},
            optional_spec={"k": "int", "symbol": "str"},
            result_spec="dict",
            effect_class=EffectClass.READ,
            source_kind=SourceKind.API,
        ),
        _search,
    )


def wire_name(name: str) -> str:
    """Dot-free wire-safe form of a tool name (OpenAI function-name rule).

    Implements: REQ-SI-FR-013 (ADR-005)
    """
    return name.replace(".", "_")


class RegistryError(RuntimeError):
    """Explicit registration-level failure (duplicate names, bad state).

    Implements: REQ-SI-INV-003 (ADR-005)
    """


class Registry:
    """Tool registration and fail-closed execution envelope.

    Implements: REQ-SI-INV-003, REQ-SI-INV-001 (ADR-005)
    """

    def __init__(self) -> None:
        """Start with an empty registration table."""
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a tool; duplicate names are refused explicitly.

        Implements: REQ-SI-INV-003 (ADR-005)
        """
        if spec.name in self._specs:
            raise RegistryError(f"tool {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def list_tools(self) -> list[ToolSpec]:
        """Return all registered specs, sorted by name.

        Implements: REQ-SI-FR-013 (ADR-005)
        """
        return sorted(self._specs.values(), key=lambda spec: spec.name)

    def openai_tool_specs(self) -> list[dict[str, Any]]:
        """Render registered specs as OpenAI function-tool definitions.

        Implements: REQ-SI-FR-013 (ADR-005)
        """
        specs: list[dict[str, Any]] = []
        for spec in self.list_tools():
            properties = {**spec.arguments_spec, **spec.optional_spec}
            required = sorted(spec.arguments_spec)
            parameters: dict[str, Any] = {
                "type": "object",
                "properties": {name: {"type": JSON_SCHEMA_TYPES[type_name]} for name, type_name in properties.items()},
            }
            if required:
                parameters["required"] = required
            specs.append(
                {
                    "type": "function",
                    "function": {
                        # Wire-safe name: OpenAI function names forbid dots.
                        "name": wire_name(spec.name),
                        "description": spec.description,
                        "parameters": parameters,
                    },
                }
            )
        return specs

    def resolve_wire_name(self, wire: str) -> str | None:
        """Map a wire-safe (dot-free) name back to its registered tool name.

        Implements: REQ-SI-FR-013 (ADR-005)
        """
        for spec in self._specs.values():
            if wire_name(spec.name) == wire:
                return spec.name
        return None

    def execute(self, call: ToolCall, *, allow_write: bool = False) -> ToolResult:
        """Execute one validated tool call; every failure is explicit.

        Fail-closed order: unknown tool -> write gate -> argument
        validation -> handler execution -> result validation. Handler
        exceptions become ok=False results — never partial results,
        never swallowed errors (INV-003). Successful results carry the
        provenance triple {tool, source_kind, produced_at} (INV-001
        groundwork).

        Implements: REQ-SI-INV-003, REQ-SI-INV-001 (ADR-005)
        """
        spec = self._specs.get(call.tool)
        if spec is None:
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=f"unknown tool {call.tool!r}; registered: {sorted(self._specs)}",
            )
        if spec.effect_class is EffectClass.WRITE and not allow_write:
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=(
                    f"tool {spec.name!r} has write effects; write tools require the "
                    "conversational confirmation flow or a CLI subcommand (blueprint §9.1)"
                ),
            )
        try:
            validate_arguments(spec, call.arguments)
        except ToolWireError as exc:
            return ToolResult(call_id=call.call_id, ok=False, error=str(exc))
        try:
            payload = self._handlers[spec.name](dict(call.arguments))
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                error=f"tool {spec.name!r} failed: {type(exc).__name__}: {exc}",
            )
        try:
            validate_result_payload(spec, payload)
        except ToolWireError as exc:
            return ToolResult(call_id=call.call_id, ok=False, error=str(exc))
        return ToolResult(
            call_id=call.call_id,
            ok=True,
            result=payload,
            provenance={
                "tool": spec.name,
                "source_kind": spec.source_kind.value,
                "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
