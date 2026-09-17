"""Shared foundation: cross-module wire types, schemas, and policy constants.

Safety-critical path (permission model G2): every change to this
package requires a linked ADR and owner approval; ADR-004 is the
charter. Nothing in this package may import other internal packages.

Implements: REQ-SI-GOV-005, REQ-SI-FR-011 (ADR-004)
"""
