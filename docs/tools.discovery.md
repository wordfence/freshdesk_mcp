# Tool Discovery

This server exposes discovery helpers so LLM clients can reliably choose the right tool:

- tools.list: Returns all available tools with summaries, use cases, safety, and doc paths.
- tools.search(query, limit?): Keyword search across names, summaries, and keywords.
- tools.explain(name): Returns the matching catalog entry plus the markdown doc body.

Docs live under the `docs/` directory; a snapshot of the Freshworks REST docs is stored under `docs/source/`.
