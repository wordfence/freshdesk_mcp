# tickets_conversations_list

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
- success, data: { conversations, summary, filtering?, resume, paging, delivery_state, guidance }, warnings?, pagination, next_call?

summary
- total_conversations (integer): Conversations returned in this response.
- total_pages_fetched (integer): Freshdesk pages fetched (partial pages count).
- total_token_count (integer): Estimated tokens consumed by the returned payload.
- complete (boolean): False when more data remains.
- ordering (string): Always `chronological_asc`.

resume
- has_more (boolean): Whether additional conversations remain.
- exhausted_token_budget (boolean): True when the global `max_tokens` halted pagination.
- next_page (integer|null): Page to request next if resuming; null when complete.
- last_conversation_id (integer|null): Anchor ID of the last conversation delivered.
- anchor (object|null): { conversation_id, position: "after" } for duplicate prevention.
- reason (string): `complete`, `more_pages`, `token_budget`, or `server_short_page`.

paging
- start_page (integer): The starting page supplied by the client.
- requested_per_page (integer): The per-page size the server honoured.
- pages_returned (integer): Count of pages (partial allowed) delivered this call.
- last_page (integer|null): The final Freshdesk page touched.
- last_page_count (integer): Conversations returned from the last page touched.
- total_conversations_returned (integer): Same as `summary.total_conversations` for convenience.
- remaining_token_budget (integer): Remaining tokens before the global limit.
- last_page_truncated (boolean): True when the final page was partial.
- page_details (array): Per-page breakdown `{ page, delivered_count, expected_count, truncated, truncated_reason? }`.

delivery_state
- truncated (boolean): True whenever the response is partial (token budget or short page).
- reason (string|null): Machine-parsable reason (e.g. `token_budget`).

guidance
- Ordered list of human-readable instructions reiterating how to resume safely.

pagination
- has_more (boolean): Mirrors `resume.has_more` for compatibility with other tools.
- next_page (integer|null): Reuse with the same `per_page` until null.
- prev_page (integer|null): Derived when the prior page index is known.

next_call (optional)
- Convenience hint for agent frameworks: when more data remains, the response includes
  `{ tool: "tickets_conversations_list", arguments: { ticket_id, page, per_page } }`.
  You can call this `tool` with the provided `arguments` to continue fetching.

Notes
- Conversations are delivered in chronological order; still maintain a seen-ID set for safety.
- Link header pagination is honoured; `paging.page_details` reflects partial pages.
- Filtering removes encrypted-report payloads and reports token savings.

Resuming
- If `resume.has_more` is true, resume with:
  - `page = resume.next_page`
  - IMPORTANT: You MUST keep `per_page` constant. DO NOT change it mid-session. Changing `per_page` will break page alignment and may lead to missing or duplicate items. The server assumes a constant `per_page` when calculating `resume.next_page`.
  - Leave `max_tokens` equal or higher if you need more data in a single call.
  - Anchor-based resume: scan the resumed page for the conversation whose `id == resume.anchor.conversation_id` and process only the items that appear after it in the page's returned order. If the anchor is not found, process the entire page.
  - Optional de-dup: maintain a client-side set of seen conversation IDs and skip any repeats to be robust to reordering or merges.

Reference
- Freshworks Support Ticket REST APIs: conversations endpoints
- docs/source/freshworks_support_ticket_rest_apis.html
