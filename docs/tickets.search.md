# tickets.search

Summary: Search tickets using Freshdesk query syntax; optional HTML stripping and result limiting.

Use when: you need to find tickets matching fields, ranges, statuses, or free text.

Parameters
- query (string, required): Freshdesk ticket search query.
- quantity (integer, optional): Limit number of returned results.
- strip_html (boolean, optional, default true): Remove HTML tags to reduce tokens.

Returns
- success, data: { results, total? }

Notes
- Freshdesk requires the entire query value to be wrapped in double quotes. When providing the string via JSON/MCP, escape the quotes. Examples:
  - query: "\"status:2\""
  - query: "\"(status:2 AND priority:1)\""
- The search endpoint supports fielded queries and operators; see Freshworks docs for syntax.

Reference
- Freshworks Support Ticket REST APIs: search tickets
- docs/source/freshworks_support_ticket_rest_apis.html
