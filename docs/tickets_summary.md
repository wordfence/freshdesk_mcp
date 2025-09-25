# tickets_summary_get / tickets_summary_update / tickets_summary_delete

Summary: View, update, or delete the summary of a Freshdesk ticket.

View Parameters
- ticket_id (integer, required)

Update Parameters
- ticket_id (integer, required)
- body (string, required): HTML content

Delete Parameters
- ticket_id (integer, required)

Returns
- success, data: summary or { message }
