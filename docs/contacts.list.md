# contacts.list

Summary: List contacts with pagination.

Parameters
- page (integer ≥1, optional)
- per_page (integer 1–100, optional)

Returns
- success, data: { contacts }, pagination, next_call?

Notes
- If `next_call` is present, call the provided tool with the given `arguments` to fetch the next page.
