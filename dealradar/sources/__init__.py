"""Source adapters and polite fetching. Adapters never touch the database (ARCHITECTURE.md §4).

May import core and normalize only. Every adapter declares its permitted access method; no
adapter for a real website exists until its access has been verified and documented in
docs/SOURCES.md.
"""
