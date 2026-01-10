"""Alternative data (alt-data) connectors + cached datasets.

Goal: bring in "soft" context (news, earnings, calendars, sentiment) in a reproducible,
auditable way that can be used as:
- an LLM risk overlay input (human-readable, linkable)
- a downstream feature set for ML (numeric, time-aligned)

Start slow: one-ticker dossier with a couple of high-signal sources.
"""

