# Freshdesk MCP Server
[![smithery badge](https://smithery.ai/badge/@effytech/freshdesk_mcp)](https://smithery.ai/server/@effytech/freshdesk_mcp)

An MCP server implementation that integrates with Freshdesk, enabling AI models to interact with Freshdesk modules and perform various support operations.

## Features

- **Freshdesk Integration**: Seamless interaction with Freshdesk API endpoints
- **AI Model Support**: Enables AI models to perform support operations through Freshdesk
- **Automated Ticket Management**: Handle ticket creation, updates, and responses

## Components

### Tools

The server offers several tools for Freshdesk operations:

- `create_ticket`: Create new support tickets
  - **Inputs**:
    - `subject` (string, required): Ticket subject
    - `description` (string, required): Ticket description
    - `source` (number, required): Ticket source code
    - `priority` (number, required): Ticket priority level
    - `status` (number, required): Ticket status code
    - `email` (string, optional): Email of the requester
    - `requester_id` (number, optional): ID of the requester
    - `custom_fields` (object, optional): Custom fields to set on the ticket

- `update_ticket`: Update existing tickets
  - **Inputs**:
    - `ticket_id` (number, required): ID of the ticket to update
    - `updates` (object, required): Fields to update

- `delete_ticket`: Delete a ticket
  - **Inputs**:
    - `ticket_id` (number, required): ID of the ticket to delete

- `search_tickets`: Search for tickets based on criteria
  - **Inputs**:
    - `query` (string, required): Search query string

- `get_ticket_fields`: Get all ticket fields
  - **Inputs**:
    - None

- `get_tickets`: Get all tickets
  - **Inputs**:
    - `page` (number, optional): Page number to fetch
    - `per_page` (number, optional): Number of tickets per page

- `get_ticket`: Get a single ticket
  - **Inputs**:
    - `ticket_id` (number, required): ID of the ticket to get

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

## License

This MCP server is licensed under the MIT License. See the LICENSE file in the project repository for full details.
