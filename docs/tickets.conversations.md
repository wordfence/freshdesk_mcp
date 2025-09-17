# tickets.conversations.list

Summary: Retrieve ticket conversations across multiple pages under a global token budget, with optional encrypted-report filtering.

Use when: you need message history for a ticket; adjust `per_page` and `max_tokens` to fit LLM context.

Parameters
- ticket_id (integer, required)
- page (integer ≥1, optional): starting page
- per_page (integer 1–100, optional): conversations per page
- filter_encrypted_reports (boolean, default true)
- report_placeholder (string, optional)
- max_tokens (integer 1–20000, default 20000): global token budget across pages
- include_html_body (boolean, default false)
- extract_links (boolean, default true)

Returns
- success, data: { conversations, summary, filtering?, resume }, warnings?

resume
- has_more (boolean): Whether more pages are available server-side.
- exhausted_token_budget (boolean): True if stop was due to the token budget.
- next_page (integer|null): Page to request next if resuming; null if complete.
- last_conversation_id (integer|null): The last conversation id included in this response.

Notes
- Link header pagination supported; use `next_page` while `has_more` is true.
- Filtering removes blocks between BEGIN/END REPORT to reduce tokens.
- Auto-pagination adapts `per_page` from observed token usage to fit within the global token budget.

Resuming
- If `resume.has_more` is true, resume with:
  - `page = resume.next_page`
  - Keep `per_page` constant (avoid gaps/overlaps)
  - Set a new `max_tokens` for the chunk as needed
  - Anchor-based resume: scan the resumed page for the conversation whose `id == last_conversation_id` and process only the items that appear after it in the page's returned order. If the anchor is not found, process the entire page.
  - Optional de-dup: maintain a client-side set of seen conversation IDs and skip any repeats to be robust to reordering or merges.

Reference
- Freshworks Support Ticket REST APIs: conversations endpoints
- docs/source/freshworks_support_ticket_rest_apis.html
