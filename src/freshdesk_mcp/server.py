import httpx
from mcp.server.fastmcp import FastMCP
import logging
import os
import base64
from typing import Optional, Dict, Union, Any
from enum import IntEnum
import re   

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize FastMCP server
mcp = FastMCP("freshdesk-mcp")

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")


def parse_link_header(link_header: str) -> Dict[str, Optional[int]]:
    """Parse the Link header to extract pagination information.
    
    Args:
        link_header: The Link header string from the response
        
    Returns:
        Dictionary containing next and prev page numbers
    """
    pagination = {
        "next": None,
        "prev": None
    }
    
    if not link_header:
        return pagination

    # Split multiple links if present
    links = link_header.split(',')
    
    for link in links:
        # Extract URL and rel
        match = re.search(r'<(.+?)>;\s*rel="(.+?)"', link)
        if match:
            url, rel = match.groups()
            # Extract page number from URL
            page_match = re.search(r'page=(\d+)', url)
            if page_match:
                page_num = int(page_match.group(1))
                pagination[rel] = page_num

    return pagination

# enums of ticket properties
class TicketSource(IntEnum):
    EMAIL = 1
    PORTAL = 2
    PHONE = 3
    CHAT = 7
    FEEDBACK_WIDGET = 9
    OUTBOUND_EMAIL = 10

class TicketStatus(IntEnum):
    OPEN = 2
    PENDING = 3
    RESOLVED = 4
    CLOSED = 5

class TicketPriority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4

@mcp.tool()
async def get_ticket_fields() -> Dict[str, Any]:
    """Get ticket fields from Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/ticket_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
    

@mcp.tool()
async def get_tickets(page: Optional[int] = 1, per_page: Optional[int] = 30) -> Dict[str, Any]:
    """Get tickets from Freshdesk with pagination support.
    
    Args:
        page: Page number to fetch (default: 1)
        per_page: Number of tickets per page (default: 30, max: 100)
    
    Returns:
        Dict containing tickets data and pagination information
    """
    # Validate input parameters
    if page < 1:
        return {"error": "Page number must be greater than 0"}
    
    if per_page < 1 or per_page > 100:
        return {"error": "Page size must be between 1 and 100"}

    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets"
    
    params = {
        "page": page,
        "per_page": per_page
    }
    
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            # Parse pagination from Link header
            link_header = response.headers.get('Link', '')
            pagination_info = parse_link_header(link_header)
            
            tickets = response.json()
            
            return {
                "tickets": tickets,
                "pagination": {
                    "current_page": page,
                    "next_page": pagination_info.get("next"),
                    "prev_page": pagination_info.get("prev"),
                    "per_page": per_page
                }
            }
            
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch tickets: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def create_ticket(
    subject: str,
    description: str,
    source: Union[int, str],
    priority: Union[int, str],
    status: Union[int, str],
    email: Optional[str] = None,
    requester_id: Optional[int] = None,
    custom_fields: Optional[Dict[str, Any]] = None
) -> str:
    """Create a ticket in Freshdesk.
    
    Args:
        subject: Subject of the ticket
        description: Description of the ticket
        source: Ticket source (1-Email, 2-Portal, 3-Phone, 7-Chat, 9-Feedback Widget, 10-Outbound Email)
        priority: Ticket priority (1-Low, 2-Medium, 3-High, 4-Urgent)
        status: Ticket status (2-Open, 3-Pending, 4-Resolved, 5-Closed)
        email: Email of the requester (either email or requester_id must be provided)
        requester_id: ID of the requester (either email or requester_id must be provided)
        custom_fields: Optional dictionary of custom fields
    
    Returns:
        str: Response message indicating success or failure
    """
    # Validate requester information
    if not email and not requester_id:
        return "Error: Either email or requester_id must be provided"

    # Convert string inputs to integers if necessary
    try:
        source_val = int(source)
        priority_val = int(priority)
        status_val = int(status)
    except ValueError:
        return "Error: Invalid value for source, priority, or status"

    # Validate enum values
    if (source_val not in [e.value for e in TicketSource] or
        priority_val not in [e.value for e in TicketPriority] or
        status_val not in [e.value for e in TicketStatus]):
        return "Error: Invalid value for source, priority, or status"

    # Prepare the request data
    data = {
        "subject": subject,
        "description": description,
        "source": source_val,
        "priority": priority_val,
        "status": status_val
    }

    # Add requester information
    if email:
        data["email"] = email
    if requester_id:
        data["requester_id"] = requester_id

    # Add custom fields if provided
    if custom_fields:
        data["custom_fields"] = custom_fields

    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            if response.status_code == 201:
                return "Ticket created successfully"
            
            response_data = response.json()
            return f"Success: {response_data}"
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                # Handle validation errors and check for mandatory custom fields
                error_data = e.response.json()
                if "errors" in error_data:
                    return f"Validation Error: {error_data['errors']}"
            return f"Error: Failed to create ticket - {str(e)}"
        except Exception as e:
            return f"Error: An unexpected error occurred - {str(e)}"
    
@mcp.tool()
async def update_ticket(ticket_id: int, ticket_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a ticket in Freshdesk with any standard or custom fields.
    
    Args:
        ticket_id: ID of the ticket to update
        **ticket_fields: Arbitrary keyword arguments for any ticket fields
            Standard fields examples:
            - subject: str
            - description: str
            - priority: int (1-4)
            - status: int (2-5)
            - source: int (1-10)
            Custom fields example:
            - custom_fields: Dict[str, Any]
    
    Returns:
        Dict containing the updated ticket information or error details
    """
    if not ticket_fields:
        return {"error": "No fields provided for update"}

    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    # Separate custom fields from standard fields
    custom_fields = ticket_fields.pop('custom_fields', {})
    
    # Prepare the update data
    update_data = {}
    
    # Add standard fields if they are provided
    for field, value in ticket_fields.items():
        update_data[field] = value
    
    # Add custom fields if they exist
    if custom_fields:
        update_data['custom_fields'] = custom_fields

    async with httpx.AsyncClient() as client:
        try:
            response = await client.put(url, headers=headers, json=update_data)
            response.raise_for_status()
            
            return {
                "success": True,
                "message": "Ticket updated successfully",
                "ticket": response.json()
            }
            
        except httpx.HTTPStatusError as e:
            error_message = f"Failed to update ticket: {str(e)}"
            try:
                error_details = e.response.json()
                if "errors" in error_details:
                    error_message = f"Validation errors: {error_details['errors']}"
            except Exception:
                pass
            return {
                "success": False,
                "error": error_message
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"An unexpected error occurred: {str(e)}"
            }
    
@mcp.tool()
async def delete_ticket(ticket_id: int) -> str:
    """Delete a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=headers)
        return response.json()
    
@mcp.tool()
async def get_ticket(ticket_id: int):
    """Get a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }   

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()  

@mcp.tool()
async def search_tickets(query: str) -> Dict[str, Any]:
    """Search for tickets in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/search/tickets"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {"query": query}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        return response.json()

def main():
    logging.info("Starting Freshdesk MCP server")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
