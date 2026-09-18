"""Ingestion adapters: market, fundamentals, news, FX (TP-009+).

Adapters are vendor-seamed (ADR-002), fail-closed (INV-003), and the
only writers of domain tables (memory-design §1). Scaffold state:
package shell only; the market adapter and call-budget guard land in
TP-009.

Implements: REQ-SI-FR-001 (ADR-002)
"""
