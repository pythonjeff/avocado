"""
lox/quiver — Quiver Quantitative integration.

v0 reads Quiver CSV exports from data/cache/quiver/ and synthesizes a morning
brief over the three signal families the user cares about: congressional
trading, government contracts, and the flow bundle (insider / WSB / OTC short).

Designed so that swapping the CSV loader for a live API client later is a
one-file change in loader.py — the readers and synthesis layer above it
operate on pandas DataFrames regardless of source.
"""
