# Freshdesk MCP Server
[![smithery badge](https://smithery.ai/badge/@effytech/freshdesk_mcp)](https://smithery.ai/server/@effytech/freshdesk_mcp)

An MCP server implementation that integrates with Freshdesk, enabling AI models to interact with Freshdesk modules and perform various support operations.

## Features

- **Freshdesk Integration**: Seamless interaction with Freshdesk API endpoints
- **AI Model Support**: Enables AI models to perform support operations through Freshdesk
- **Automated Ticket Management**: Handle ticket creation, updates, and responses
- **Health Endpoint**: `server_info` reports version and readiness
- **Consistent Schemas**: Standardized tool responses with `success`, `data`, `pagination`, `warnings`, `error`
- **Resilience**: Built‑in retries, timeouts, and rate‑limit handling

## Components

### Tools

The server offers tools for Freshdesk operations (read/write), and discovery helpers to aid LLM tool selection. All tools return a consistent shape: `{ success, data, pagination?, warnings?, error? }`.

Naming and discovery:
- Tool names follow a `domain.verb` convention (e.g., `tickets_create`, `contacts_search`).
Discovery helpers:
- `tools_list` — list available tools with summaries and doc paths
- `tools_search(query, limit?)` — search by name/keywords/summary
- `tools_explain(name)` — return catalog entry plus full markdown docs

Documentation:
- Short, LLM-focused docs live under `docs/` (e.g., docs/tickets_create.md)
- Snapshot of Freshworks REST docs: `docs/source/freshworks_support_ticket_rest_apis.html`

The server’s main tools include (see `docs/` for details):

- Tickets: `tickets_create`, `tickets_update`, `tickets_delete`, `tickets_get`, `tickets_list`, `tickets_search`
- Ticket conversations: `tickets_conversations_list` (multi-page with token budget and resume metadata), `tickets_reply_create`, `tickets_note_create`, `tickets_conversation_update`
- Ticket summaries: `tickets_summary_get`, `tickets_summary_update`, `tickets_summary_delete`
- Ticket fields: `fields_tickets_list`, `fields_tickets_create`, `fields_tickets_get`, `fields_tickets_update`, `fields_tickets_get_property`
- Contacts: `contacts_list`, `contacts_get`, `contacts_search`, `contacts_update`
- Contact fields: `fields_contacts_list`, `fields_contacts_get`, `fields_contacts_create`, `fields_contacts_update`
- Companies: `companies_list`, `companies_get`, `companies_search`, `companies_find_by_name`, `fields_companies_list`
- Agents: `agents_list`, `agents_get`, `agents_search`, `agents_create`, `agents_update`
- Groups: `groups_list`, `groups_get`, `groups_create`, `groups_update`
- Canned responses: `canned_folders_list`, `canned_folders_create`, `canned_folders_update`, `canned_list`, `canned_get`, `canned_create`, `canned_update`
- Solutions: `solutions_categories_list`, `solutions_categories_get`, `solutions_categories_create`, `solutions_categories_update`, `solutions_folders_list`, `solutions_folders_get`, `solutions_folders_create`, `solutions_folders_update`, `solutions_articles_list`, `solutions_articles_get`, `solutions_articles_create`, `solutions_articles_update`

## Getting Started

### Installing via Smithery

To install freshdesk_mcp for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@effytech/freshdesk_mcp):

```bash
npx -y @smithery/cli install @effytech/freshdesk_mcp --client claude
```

### Prerequisites

- A Freshdesk account (sign up at [freshdesk.com](https://freshdesk.com))
- Freshdesk API key
- `uvx` installed (`pip install uv` or `brew install uv`)

### Configuration

1. Generate your Freshdesk API key from the Freshdesk admin panel
2. Set up your domain and authentication details

### Usage with Claude Desktop

1. Install Claude Desktop if you haven't already
2. Add the following configuration to your `claude_desktop_config.json`:

```json
"mcpServers": {
  "freshdesk-mcp": {
    "command": "uvx",
    "args": [
        "freshdesk-mcp"
    ],
    "env": {
      "FRESHDESK_API_KEY": "<YOUR_FRESHDESK_API_KEY>",
      "FRESHDESK_DOMAIN": "<YOUR_FRESHDESK_DOMAIN>"
    }
  }
}
```

**Important Notes**:
- Replace `YOUR_FRESHDESK_API_KEY` with your actual Freshdesk API key
- Replace `YOUR_FRESHDESK_DOMAIN` with your Freshdesk domain (e.g., `yourcompany.freshdesk.com`)
 - Ensure `FRESHDESK_DOMAIN` does not include a scheme (no `https://`)

## Example Operations

Once configured, you can ask Claude to perform operations like:

- "Create a new ticket with subject 'Payment Issue for customer A101' and description as 'Reaching out for a payment issue in the last month for customer A101', where customer email is a101@acme.com and set priority to high"
- "Update the status of ticket #12345 to 'Resolved'"
- "List all high-priority tickets assigned to the agent John Doe"
- "List previous tickets of customer A101 in last 30 days"


## Testing

For testing purposes, you can start the server manually:

```bash
uvx freshdesk-mcp --env FRESHDESK_API_KEY=<your_api_key> --env FRESHDESK_DOMAIN=<your_domain>
```

## Troubleshooting

- Verify your Freshdesk API key and domain are correct
- Ensure proper network connectivity to Freshdesk servers
- Check API rate limits and quotas
- Verify the `uvx` command is available in your PATH
- Use `tools_search("<goal>")` or `tools_list` to locate the right tool

## License

This MCP server is licensed under the MIT License. See the LICENSE file in the project repository for full details.
