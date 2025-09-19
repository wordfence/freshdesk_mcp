# tickets.conversations.list

Summary: Retrieve ticket conversations across multiple pages under a global token budget, with optional encrypted-report filtering.

Use when: you need message history for a ticket; adjust `per_page` and `max_tokens` to fit LLM context.

Critical warning
- NEVER change `per_page` between successive calls in the same paging session. Doing so will misalign Freshdesk pages and can cause skipped or duplicated conversations. Always reuse the exact `per_page` you started with. If you must change `per_page`, restart from `page = 1` (or rebuild a seen-ID set and re-fetch overlapping pages) to avoid data loss.

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
- success, data: { conversations, summary, filtering?, resume }, warnings?, pagination, next_call?

resume
- has_more (boolean): Whether more pages are available server-side.
- exhausted_token_budget (boolean): True if stop was due to the token budget.
- next_page (integer|null): Page to request next if resuming; null if complete.
- last_conversation_id (integer|null): The last conversation id included in this response.

pagination
- has_more (boolean): Same as `resume.has_more`, exposed at top-level for consistency with other list tools.
- next_page (integer|null): Call this tool again with `page = next_page` while not null.
- prev_page (integer|null, optional): Provided when available.

next_call (optional)
- Convenience hint for agent frameworks: when more data remains, the response includes
  `{ tool: "tickets.conversations.list", arguments: { ticket_id, page, per_page } }`.
  You can call this `tool` with the provided `arguments` to continue fetching.

Notes
- Link header pagination supported; use `next_page` while `has_more` is true.
- Filtering removes blocks between BEGIN/END REPORT to reduce tokens.
- Auto-pagination adapts `per_page` from observed token usage to fit within the global token budget.

Resuming
- If `pagination.has_more` (or `resume.has_more`) is true, resume with:
  - `page = resume.next_page`
  - IMPORTANT: You MUST keep `per_page` constant. DO NOT change it mid-session. Changing `per_page` will break page alignment and may lead to missing or duplicate items. The server assumes a constant `per_page` when calculating `resume.next_page`.
  - Set a new `max_tokens` for the chunk as needed
  - Anchor-based resume: scan the resumed page for the conversation whose `id == last_conversation_id` and process only the items that appear after it in the page's returned order. If the anchor is not found, process the entire page.
  - Optional de-dup: maintain a client-side set of seen conversation IDs and skip any repeats to be robust to reordering or merges.

Reference
- Freshworks Support Ticket REST APIs: conversations endpoints
- docs/source/freshworks_support_ticket_rest_apis.html
