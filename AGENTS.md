# Repository instructions

Keep checks scoped to the supplied compiled library and declared adapter.
Metadata and parameter validation are the only native calls permitted here.
Do not add electrical stepping, simulator integration or qualification claims
without a separately reviewed design and evidence.

Preserve third-party notices. Keep changes and comments concise. Add a deliberate
software fixture for a new failure mode and run `python -m unittest discover -s
tests -v`. Never describe a platform as tested unless its native CI executed.

Do not infer authority to publish or message maintainers from this file. Use the
session's explicit publication scope. Commit by named paths; preserve others'
work. Wattness is the sole public author and committer; no co-author trailers.
