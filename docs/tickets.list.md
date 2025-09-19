# tickets.list

Summary: List Freshdesk tickets with pagination.

Parameters
- page (integer ≥1, optional)
- per_page (integer 1–100, optional)

Returns
- success, data: { tickets }, pagination, next_call?

Notes
- If `next_call` is present, call the provided tool with the given `arguments` to fetch the next page.

Reference
- See docs/common.md and Freshworks REST docs snapshot.
