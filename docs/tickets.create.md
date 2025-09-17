# tickets.create

Summary: Create a Freshdesk ticket for a requester using standard and custom fields.

Use when: starting a new support case; do not use for updates to existing tickets.

Parameters
- subject (string, required): Short summary.
- description (string, required): Ticket body; HTML allowed.
- source (enum, required): EMAIL, PORTAL, PHONE, CHAT, FEEDBACK_WIDGET, OUTBOUND_EMAIL.
- priority (enum, required): LOW, MEDIUM, HIGH, URGENT.
- status (enum, required): OPEN, PENDING, RESOLVED, CLOSED.
- email (string, optional): Requester email (format: email) if no requester_id.
- requester_id (integer, optional): Requester id if no email.
- custom_fields (object, optional): Field key/value pairs.
- additional_fields (object, optional): Any other top-level fields (advanced).

Returns
- success, data: { ticket? }, warnings?

Notes
- Either email or requester_id is required.
- See ticket fields and system fields in Freshworks docs.

Reference
- Freshworks Support Ticket REST APIs: create/update ticket endpoints.
- docs/source/freshworks_support_ticket_rest_apis.html
