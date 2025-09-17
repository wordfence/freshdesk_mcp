# tickets.update

Summary: Update a Freshdesk ticket’s fields, including status, priority, type, assignee, and custom fields.

Use when: modifying an existing ticket; do not use for creating tickets.

Parameters
- ticket_id (integer, required)
- ticket_fields (object, required): Allowed top-level fields and custom_fields.

Returns
- success, data: { message, ticket }, or error with validation details

Notes
- Validation errors include field-specific messages.
- Partial updates supported; only include fields to change.

Reference
- Freshworks Support Ticket REST APIs: update ticket
- docs/source/freshworks_support_ticket_rest_apis.html
