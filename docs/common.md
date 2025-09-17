# Common Reference

This server’s tools were informed by the Freshworks Support Ticket REST API documentation.

Source (fetched): docs/source/freshworks_support_ticket_rest_apis.html

Key points
- Pagination: `page`, `per_page`; use `Link` header (`rel="next"`, `rel="prev"`).
- Rate limits: HTTP 429 with `Retry-After`; use exponential backoff.
- Ticket fields: system fields (status, priority, source, type) and custom_fields.
- Conversations: list replies/notes; supports paging; bodies may be HTML.
- Search syntax: fielded filters, ranges, operators; returns `results` array with matches.

Enums used by tools
- status: OPEN, PENDING, RESOLVED, CLOSED
- priority: LOW, MEDIUM, HIGH, URGENT
- source: EMAIL, PORTAL, PHONE, CHAT, FEEDBACK_WIDGET, OUTBOUND_EMAIL

Safety
- Write operations note side effects; consider `dry_run` patterns in clients for preview.
