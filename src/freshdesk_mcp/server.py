import httpx
from mcp.server.fastmcp import FastMCP
import logging
import os
import base64
from typing import Optional, Dict, Union, Any, List
from enum import IntEnum, Enum
import re
from pydantic import BaseModel, Field
import json

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize FastMCP server
mcp = FastMCP("freshdesk-mcp")

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")


def filter_encrypted_reports(text: str, placeholder: str = "[ENCRYPTED REPORT REMOVED]") -> str:
    """Remove encrypted blocks between -----BEGIN REPORT----- and -----END REPORT----- tags.
    
    Args:
        text: The text containing encrypted reports
        placeholder: Text to replace the encrypted blocks with
        
    Returns:
        Text with encrypted reports removed
    """
    if not text or "-----BEGIN REPORT-----" not in text:
        return text
    
    pattern = r'-----BEGIN REPORT-----.*?-----END REPORT-----'
    filtered_text = re.sub(pattern, placeholder, text, flags=re.DOTALL)
    return filtered_text


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.
    
    Uses the approximation of 1 token ≈ 4 characters.
    
    Args:
        text: The text to estimate tokens for
        
    Returns:
        Estimated number of tokens
    """
    return len(text) // 4


def process_conversation_body(conversation: Dict[str, Any], filter_reports: bool = True, 
                            report_placeholder: str = "[ENCRYPTED REPORT REMOVED]") -> Dict[str, Any]:
    """Process a conversation to optionally filter encrypted reports.
    
    Args:
        conversation: The conversation dictionary
        filter_reports: Whether to filter encrypted reports
        report_placeholder: Text to replace encrypted reports with
        
    Returns:
        Processed conversation dictionary
    """
    if not filter_reports:
        return conversation
    
    # Create a copy to avoid modifying the original
    processed = conversation.copy()
    
    # Fields that might contain encrypted reports
    fields_to_filter = ['body', 'body_text', 'description']
    
    for field in fields_to_filter:
        if field in processed and processed[field]:
            original_text = processed[field]
            filtered_text = filter_encrypted_reports(original_text, report_placeholder)
            processed[field] = filtered_text
    
    return processed


def extract_links_from_html(html: str) -> List[Dict[str, str]]:
    """Extract anchor links from an HTML string.

    Returns a list of {"text": str, "url": str} for each <a href>.
    Uses Python's standard html.parser for zero-dependency parsing.
    """
    from html.parser import HTMLParser

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self._in_a = False
            self._current_href = None
            self._current_text_parts: List[str] = []
            self.links: List[Dict[str, str]] = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() == 'a':
                href = None
                for k, v in attrs:
                    if k.lower() == 'href':
                        href = v
                        break
                self._in_a = True
                self._current_href = href
                self._current_text_parts = []

        def handle_data(self, data):
            if self._in_a and data:
                self._current_text_parts.append(data)

        def handle_endtag(self, tag):
            if tag.lower() == 'a' and self._in_a:
                text = ''.join(self._current_text_parts).strip()
                href = self._current_href or ''
                if href:
                    self.links.append({"text": text, "url": href})
                self._in_a = False
                self._current_href = None
                self._current_text_parts = []

    if not html or '<a' not in html.lower():
        return []

    parser = LinkParser()
    try:
        parser.feed(html)
    except Exception:
        # Be resilient to malformed HTML; return what we could parse
        pass
    return parser.links


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
class AgentTicketScope(IntEnum):
    GLOBAL_ACCESS = 1
    GROUP_ACCESS = 2
    RESTRICTED_ACCESS = 3

class UnassignedForOptions(str, Enum):
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    EIGHT_HOURS = "8h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"
    TWO_DAYS = "2d"
    THREE_DAYS = "3d"

class GroupCreate(BaseModel):
    name: str = Field(..., description="Name of the group")
    description: Optional[str] = Field(None, description="Description of the group")
    agent_ids: Optional[List[int]] = Field(
        default=None,
        description="Array of agent user ids"
    )
    auto_ticket_assign: Optional[int] = Field(
        default=0,
        ge=0,
        le=1,
        description="Automatic ticket assignment type (0 or 1)"
    )
    escalate_to: Optional[int] = Field(
        None,
        description="User ID to whom escalation email is sent if ticket is unassigned"
    )
    unassigned_for: Optional[UnassignedForOptions] = Field(
        default=UnassignedForOptions.THIRTY_MIN,
        description="Time after which escalation email will be sent"
    )

class ContactFieldCreate(BaseModel):
    label: str = Field(..., description="Display name for the field (as seen by agents)")
    label_for_customers: str = Field(..., description="Display name for the field (as seen by customers)")
    type: str = Field(
        ...,
        description="Type of the field",
        pattern="^(custom_text|custom_paragraph|custom_checkbox|custom_number|custom_dropdown|custom_phone_number|custom_url|custom_date)$"
    )
    editable_in_signup: bool = Field(
        default=False,
        description="Set to true if the field can be updated by customers during signup"
    )
    position: int = Field(
        default=1,
        description="Position of the company field"
    )
    required_for_agents: bool = Field(
        default=False,
        description="Set to true if the field is mandatory for agents"
    )
    customers_can_edit: bool = Field(
        default=False,
        description="Set to true if the customer can edit the fields in the customer portal"
    )
    required_for_customers: bool = Field(
        default=False,
        description="Set to true if the field is mandatory in the customer portal"
    )
    displayed_for_customers: bool = Field(
        default=False,
        description="Set to true if the customers can see the field in the customer portal"
    )
    choices: Optional[List[Dict[str, Union[str, int]]]] = Field(
        default=None,
        description="Array of objects in format {'value': 'Choice text', 'position': 1} for dropdown choices"
    )

class CannedResponseCreate(BaseModel):
    title: str = Field(..., description="Title of the canned response")
    content_html: str = Field(..., description="HTML version of the canned response content")
    folder_id: int = Field(..., description="Folder where the canned response gets added")
    visibility: int = Field(
        ...,
        description="Visibility of the canned response (0=all agents, 1=personal, 2=select groups)",
        ge=0,
        le=2
    )
    group_ids: Optional[List[int]] = Field(
        None,
        description="Groups for which the canned response is visible. Required if visibility=2"
    )

@mcp.tool()
async def get_ticket_fields() -> Dict[str, Any]:
    """Get ticket fields from Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/ticket_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()


@mcp.tool()
async def get_tickets(page: Optional[int] = 1, per_page: Optional[int] = 30) -> Dict[str, Any]:
    """Get tickets from Freshdesk with pagination support."""
    # Validate input parameters
    if page < 1:
        return {"error": "Page number must be greater than 0"}

    if per_page < 1 or per_page > 100:
        return {"error": "Page size must be between 1 and 100"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets"

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
    custom_fields: Optional[Dict[str, Any]] = None,
    additional_fields: Optional[Dict[str, Any]] = None  # 👈 new parameter
) -> str:
    """Create a ticket in Freshdesk"""
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

     # Add any other top-level fields
    if additional_fields:
        data.update(additional_fields)

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets"
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
    """Update a ticket in Freshdesk."""
    if not ticket_fields:
        return {"error": "No fields provided for update"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}"
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
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=headers)
        return response.json()

@mcp.tool()
async def get_ticket(ticket_id: int):
    """Get a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def search_tickets(query: str, quantity: int | None = None) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Search for tickets in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/search/tickets"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {"query": query}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        if quantity:
            print(response.json().keys())
            return response.json()["results"][0:quantity - 1]
        else:
            return response.json()

@mcp.tool()
async def get_ticket_conversation(
    ticket_id: int,
    page: Optional[int] = 1,
    per_page: Optional[int] = 10,
    filter_encrypted_reports: Optional[bool] = True,
    report_placeholder: Optional[str] = "[ENCRYPTED REPORT REMOVED]",
    max_tokens: Optional[int] = 20000,
    include_html_body: Optional[bool] = False,
    extract_links: Optional[bool] = True
) -> Dict[str, Any]:
    """Get ticket conversations with pagination and token limit support.
    
    Args:
        ticket_id: The ID of the ticket
        page: Page number (starts at 1)
        per_page: Number of conversations per page (max 100, default 10)
        filter_encrypted_reports: Whether to remove encrypted report blocks
        report_placeholder: Text to replace encrypted reports with
        max_tokens: Maximum tokens to return (default 20000)
        
    Returns:
        Dictionary containing conversations and pagination metadata
    """
    # Validate input parameters
    if page < 1:
        return {"error": "Page number must be greater than 0"}
    
    if per_page < 1 or per_page > 100:
        return {"error": "Page size must be between 1 and 100"}
    
    if max_tokens > 20000:
        return {"error": "Maximum tokens cannot exceed 20000"}
    
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/conversations"
    
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
            
            conversations = response.json()
            
            # Process conversations and check token limits
            processed_conversations = []
            total_tokens = 0
            tokens_saved = 0
            reports_found = 0
            truncated = False
            
            for conv in conversations:
                # Process the conversation (filter reports if requested)
                processed_conv = process_conversation_body(
                    conv, 
                    filter_reports=filter_encrypted_reports,
                    report_placeholder=report_placeholder
                )
                
                # Count reports found
                for field in ['body', 'body_text', 'description']:
                    if field in conv and conv[field] and "-----BEGIN REPORT-----" in conv[field]:
                        reports_found += 1
                        # Estimate tokens saved
                        original_tokens = estimate_tokens(conv[field])
                        filtered_tokens = estimate_tokens(processed_conv[field])
                        tokens_saved += (original_tokens - filtered_tokens)

                # Optionally extract links from HTML body
                if extract_links and 'body' in processed_conv and processed_conv['body']:
                    links = extract_links_from_html(processed_conv['body'])
                    if links:
                        processed_conv['links'] = links
                
                # Optionally drop the HTML body to reduce tokens
                if not include_html_body and 'body' in processed_conv:
                    # Keep links (added above) but remove the HTML markup-heavy body
                    processed_conv.pop('body', None)
                
                # Estimate tokens for this conversation
                conv_json = json.dumps(processed_conv)
                conv_tokens = estimate_tokens(conv_json)
                
                # Check if adding this conversation would exceed token limit
                if total_tokens + conv_tokens > max_tokens:
                    truncated = True
                    break
                
                processed_conversations.append(processed_conv)
                total_tokens += conv_tokens
            
            result = {
                "conversations": processed_conversations,
                "pagination": {
                    "current_page": page,
                    "next_page": pagination_info.get("next"),
                    "prev_page": pagination_info.get("prev"),
                    "per_page": per_page,
                    "items_returned": len(processed_conversations),
                    "has_more": pagination_info.get("next") is not None or truncated,
                    "token_count": total_tokens,
                    "truncated": truncated
                }
            }
            
            # Add filtering info if reports were filtered
            if filter_encrypted_reports:
                result["filtering"] = {
                    "encrypted_reports_removed": True,
                    "reports_found": reports_found,
                    "tokens_saved": tokens_saved
                }
            
            # Add warnings if needed
            warnings = []
            if truncated:
                warnings.append(f"Response truncated to stay under {max_tokens} token limit. Use smaller per_page value or increase max_tokens.")
            if len(warnings) > 0:
                result["warnings"] = warnings
            
            return result
            
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch conversations: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def get_all_ticket_conversations(
    ticket_id: int,
    filter_encrypted_reports: Optional[bool] = True,
    report_placeholder: Optional[str] = "[ENCRYPTED REPORT REMOVED]",
    max_total_tokens: Optional[int] = 20000,
    include_html_body: Optional[bool] = False,
    extract_links: Optional[bool] = True
) -> Dict[str, Any]:
    """Get all ticket conversations with automatic pagination to stay under token limit.
    
    This function automatically fetches multiple pages of conversations while
    ensuring the total response stays under the token limit.
    
    Args:
        ticket_id: The ID of the ticket
        filter_encrypted_reports: Whether to remove encrypted report blocks
        report_placeholder: Text to replace encrypted reports with
        max_total_tokens: Maximum total tokens to return (default 20000)
        
    Returns:
        Dictionary containing all conversations that fit within token limit
    """
    all_conversations = []
    total_tokens = 0
    current_page = 1
    per_page = 10  # Start conservative
    has_more = True
    total_reports_found = 0
    total_tokens_saved = 0
    
    while has_more and total_tokens < max_total_tokens:
        # Calculate remaining token budget
        remaining_tokens = max_total_tokens - total_tokens
        logging.info(f"remaining_tokens: {remaining_tokens}")
        
        # Fetch a page of conversations
        result = await get_ticket_conversation(
            ticket_id=ticket_id,
            page=current_page,
            per_page=per_page,
            filter_encrypted_reports=filter_encrypted_reports,
            report_placeholder=report_placeholder,
            max_tokens=remaining_tokens,
            include_html_body=include_html_body,
            extract_links=extract_links
        )
        logging.info(f"result: {result}")
        
        # Check for errors
        if "error" in result:
            return result
        
        # Add conversations from this page
        conversations = result.get("conversations", [])
        all_conversations.extend(conversations)
        
        # Update totals
        pagination = result.get("pagination", {})
        total_tokens += pagination.get("token_count", 0)
        
        # Update filtering stats
        if "filtering" in result:
            filtering = result["filtering"]
            total_reports_found += filtering.get("reports_found", 0)
            total_tokens_saved += filtering.get("tokens_saved", 0)
        
        # Check if there are more pages
        has_more = pagination.get("has_more", False)
        current_page += 1
        
        # Adjust per_page based on token usage
        if len(conversations) > 0:
            avg_tokens_per_conv = pagination.get("token_count", 0) / len(conversations)
            if avg_tokens_per_conv > 0:
                # Calculate optimal per_page for next request
                safe_per_page = min(100, int(remaining_tokens / avg_tokens_per_conv * 0.8))
                per_page = max(1, safe_per_page)
    
    return {
        "conversations": all_conversations,
        "summary": {
            "total_conversations": len(all_conversations),
            "total_pages_fetched": current_page - 1,
            "total_token_count": total_tokens,
            "complete": not has_more or total_tokens >= max_total_tokens
        },
        "filtering": {
            "encrypted_reports_removed": filter_encrypted_reports,
            "total_reports_found": total_reports_found,
            "total_tokens_saved": total_tokens_saved
        }
    }


@mcp.tool()
async def create_ticket_reply(ticket_id: int,body: str)-> Dict[str, Any]:
    """Create a reply to a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/reply"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {
        "body": body
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        return response.json()

@mcp.tool()
async def create_ticket_note(ticket_id: int,body: str)-> Dict[str, Any]:
    """Create a note for a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/notes"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {
        "body": body
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        return response.json()

@mcp.tool()
async def update_ticket_conversation(conversation_id: int,body: str)-> Dict[str, Any]:
    """Update a conversation for a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/conversations/{conversation_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {
        "body": body
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=data)
        status_code = response.status_code
        if status_code == 200:
            return response.json()
        else:
            return f"Cannot update conversation ${response.json()}"

@mcp.tool()
async def get_agents(page: Optional[int] = 1, per_page: Optional[int] = 30)-> list[Dict[str, Any]]:
    """Get all agents in Freshdesk with pagination support."""
    # Validate input parameters
    if page < 1:
        return {"error": "Page number must be greater than 0"}

    if per_page < 1 or per_page > 100:
        return {"error": "Page size must be between 1 and 100"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {
        "page": page,
        "per_page": per_page
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        return response.json()

@mcp.tool()
async def list_contacts(page: Optional[int] = 1, per_page: Optional[int] = 30)-> list[Dict[str, Any]]:
    """List all contacts in Freshdesk with pagination support."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contacts"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {
        "page": page,
        "per_page": per_page
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        return response.json()

@mcp.tool()
async def get_contact(contact_id: int)-> Dict[str, Any]:
    """Get a contact in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contacts/{contact_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def search_contacts(query: str)-> list[Dict[str, Any]]:
    """Search for contacts in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contacts/autocomplete"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {"term": query}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        return response.json()

@mcp.tool()
async def update_contact(contact_id: int, contact_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a contact in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contacts/{contact_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {}
    for field, value in contact_fields.items():
        data[field] = value
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=data)
        return response.json()
@mcp.tool()
async def list_canned_responses(folder_id: int)-> list[Dict[str, Any]]:
    """List all canned responses in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_response_folders/{folder_id}/responses"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    canned_responses = []
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        for canned_response in response.json():
            canned_responses.append(canned_response)
    return canned_responses

@mcp.tool()
async def list_canned_response_folders()-> list[Dict[str, Any]]:
    """List all canned response folders in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_response_folders"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def view_canned_response(canned_response_id: int)-> Dict[str, Any]:
    """View a canned response in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_responses/{canned_response_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
@mcp.tool()
async def create_canned_response(canned_response_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a canned response in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = CannedResponseCreate(**canned_response_fields)
        # Convert to dict for API request
        canned_response_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_responses"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=canned_response_data)
        return response.json()

@mcp.tool()
async def update_canned_response(canned_response_id: int, canned_response_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a canned response in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_responses/{canned_response_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=canned_response_fields)
        return response.json()
@mcp.tool()
async def create_canned_response_folder(name: str)-> Dict[str, Any]:
    """Create a canned response folder in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_response_folders"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {
        "name": name
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        return response.json()
@mcp.tool()
async def update_canned_response_folder(folder_id: int, name: str)-> Dict[str, Any]:
    """Update a canned response folder in Freshdesk."""
    print(folder_id, name)
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/canned_response_folders/{folder_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {
        "name": name
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=data)
        return response.json()

@mcp.tool()
async def list_solution_articles(folder_id: int)-> list[Dict[str, Any]]:
    """List all solution articles in Freshdesk."""
    solution_articles = []
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/folders/{folder_id}/articles"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        for article in response.json():
            solution_articles.append(article)
    return solution_articles

@mcp.tool()
async def list_solution_folders(category_id: int)-> list[Dict[str, Any]]:
    if not category_id:
        return {"error": "Category ID is required"}
    """List all solution folders in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories/{category_id}/folders"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def list_solution_categories()-> list[Dict[str, Any]]:
    """List all solution categories in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def view_solution_category(category_id: int)-> Dict[str, Any]:
    """View a solution category in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories/{category_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def create_solution_category(category_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution category in Freshdesk."""
    if not category_fields.get("name"):
        return {"error": "Name is required"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=category_fields)
        return response.json()

@mcp.tool()
async def update_solution_category(category_id: int, category_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution category in Freshdesk."""
    if not category_fields.get("name"):
        return {"error": "Name is required"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories/{category_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=category_fields)
        return response.json()

@mcp.tool()
async def create_solution_category_folder(category_id: int, folder_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution category folder in Freshdesk."""
    if not folder_fields.get("name"):
        return {"error": "Name is required"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/categories/{category_id}/folders"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=folder_fields)
        return response.json()

@mcp.tool()
async def view_solution_category_folder(folder_id: int)-> Dict[str, Any]:
    """View a solution category folder in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/folders/{folder_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
@mcp.tool()
async def update_solution_category_folder(folder_id: int, folder_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution category folder in Freshdesk."""
    if not folder_fields.get("name"):
        return {"error": "Name is required"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/folders/{folder_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=folder_fields)
        return response.json()


@mcp.tool()
async def create_solution_article(folder_id: int, article_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution article in Freshdesk."""
    if not article_fields.get("title") or not article_fields.get("status") or not article_fields.get("description"):
        return {"error": "Title, status and description are required"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/folders/{folder_id}/articles"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=article_fields)
        return response.json()

@mcp.tool()
async def view_solution_article(article_id: int)-> Dict[str, Any]:
    """View a solution article in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/articles/{article_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def update_solution_article(article_id: int, article_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution article in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/solutions/articles/{article_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=article_fields)
        return response.json()

@mcp.tool()
async def view_agent(agent_id: int)-> Dict[str, Any]:
    """View an agent in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents/{agent_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def create_agent(agent_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create an agent in Freshdesk."""
    # Validate mandatory fields
    if not agent_fields.get("email") or not agent_fields.get("ticket_scope"):
        return {
            "error": "Missing mandatory fields. Both 'email' and 'ticket_scope' are required."
        }
    if agent_fields.get("ticket_scope") not in [e.value for e in AgentTicketScope]:
        return {
            "error": "Invalid value for ticket_scope. Must be one of: " + ", ".join([e.name for e in AgentTicketScope])
        }

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=agent_fields)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Failed to create agent: {str(e)}",
                "details": e.response.json() if e.response else None
            }

@mcp.tool()
async def update_agent(agent_id: int, agent_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an agent in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents/{agent_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=agent_fields)
        return response.json()

@mcp.tool()
async def search_agents(query: str) -> list[Dict[str, Any]]:
    """Search for agents in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents/autocomplete?term={query}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
@mcp.tool()
async def list_groups(page: Optional[int] = 1, per_page: Optional[int] = 30)-> list[Dict[str, Any]]:
    """List all groups in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/groups"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    params = {
        "page": page,
        "per_page": per_page
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        return response.json()

@mcp.tool()
async def create_group(group_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a group in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = GroupCreate(**group_fields)
        # Convert to dict for API request
        group_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/groups"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=group_data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Failed to create group: {str(e)}",
                "details": e.response.json() if e.response else None
            }

@mcp.tool()
async def view_group(group_id: int) -> Dict[str, Any]:
    """View a group in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/groups/{group_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def create_ticket_field(ticket_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a ticket field in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/admin/ticket_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=ticket_field_fields)
        return response.json()
@mcp.tool()
async def view_ticket_field(ticket_field_id: int) -> Dict[str, Any]:
    """View a ticket field in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/admin/ticket_fields/{ticket_field_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def update_ticket_field(ticket_field_id: int, ticket_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a ticket field in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/admin/ticket_fields/{ticket_field_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=ticket_field_fields)
        return response.json()

@mcp.tool()
async def update_group(group_id: int, group_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a group in Freshdesk."""
    try:
        validated_fields = GroupCreate(**group_fields)
        # Convert to dict for API request
        group_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/groups/{group_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.put(url, headers=headers, json=group_data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Failed to update group: {str(e)}",
                "details": e.response.json() if e.response else None
            }

@mcp.tool()
async def list_contact_fields()-> list[Dict[str, Any]]:
    """List all contact fields in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contact_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def view_contact_field(contact_field_id: int) -> Dict[str, Any]:
    """View a contact field in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contact_fields/{contact_field_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()

@mcp.tool()
async def create_contact_field(contact_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a contact field in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = ContactFieldCreate(**contact_field_fields)
        # Convert to dict for API request
        contact_field_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contact_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=contact_field_data)
        return response.json()

@mcp.tool()
async def update_contact_field(contact_field_id: int, contact_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a contact field in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/contact_fields/{contact_field_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=contact_field_fields)
        return response.json()
@mcp.tool()
async def get_field_properties(field_name: str):
    """Get properties of a specific field by name."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/ticket_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    actual_field_name=field_name
    if field_name == "type":
        actual_field_name="ticket_type"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()  # Raise error for bad status codes
        fields = response.json()
    # Filter the field by name
    matched_field = next((field for field in fields if field["name"] == actual_field_name), None)

    return matched_field

@mcp.prompt()
def create_ticket(
    subject: str,
    description: str,
    source: str,
    priority: str,
    status: str,
    email: str
) -> str:
    """Create a ticket in Freshdesk"""
    payload = {
        "subject": subject,
        "description": description,
        "source": source,
        "priority": priority,
        "status": status,
        "email": email,
    }
    return f"""
Kindly create a ticket in Freshdesk using the following payload:

{payload}

If you need to retrieve information about any fields (such as allowed values or internal keys), please use the `get_field_properties()` function.

Notes:
- The "type" field is **not** a custom field; it is a standard system field.
- The "type" field is required but should be passed as a top-level parameter, not within custom_fields.
Make sure to reference the correct keys from `get_field_properties()` when constructing the payload.
"""

@mcp.prompt()
def create_reply(
    ticket_id:int,
    reply_message: str,
) -> str:
    """Create a reply in Freshdesk"""
    payload = {
        "body":reply_message,
    }
    return f"""
Kindly create a ticket reply in Freshdesk for ticket ID {ticket_id} using the following payload:

{payload}

Notes:
- The "body" field must be in **HTML format** and should be **brief yet contextually complete**.
- When composing the "body", please **review the previous conversation** in the ticket.
- Ensure the tone and style **match the prior replies**, and that the message provides **full context** so the recipient can understand the issue without needing to re-read earlier messages.
"""

@mcp.tool()
async def list_companies(page: Optional[int] = 1, per_page: Optional[int] = 30) -> Dict[str, Any]:
    """List all companies in Freshdesk with pagination support."""
    # Validate input parameters
    if page < 1:
        return {"error": "Page number must be greater than 0"}

    if per_page < 1 or per_page > 100:
        return {"error": "Page size must be between 1 and 100"}

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/companies"

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

            companies = response.json()

            return {
                "companies": companies,
                "pagination": {
                    "current_page": page,
                    "next_page": pagination_info.get("next"),
                    "prev_page": pagination_info.get("prev"),
                    "per_page": per_page
                }
            }

        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch companies: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def view_company(company_id: int) -> Dict[str, Any]:
    """Get a company in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/companies/{company_id}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch company: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def search_companies(query: str) -> Dict[str, Any]:
    """Search for companies in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/companies/autocomplete"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }
    # Use the name parameter as specified in the API
    params = {"name": query}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to search companies: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def find_company_by_name(name: str) -> Dict[str, Any]:
    """Find a company by name in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/companies/autocomplete"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }
    params = {"name": name}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to find company: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def list_company_fields() -> List[Dict[str, Any]]:
    """List all company fields in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/company_fields"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch company fields: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def view_ticket_summary(ticket_id: int) -> Dict[str, Any]:
    """Get the summary of a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/summary"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch ticket summary: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def update_ticket_summary(ticket_id: int, body: str) -> Dict[str, Any]:
    """Update the summary of a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/summary"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }
    data = {
        "body": body
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.put(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to update ticket summary: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def delete_ticket_summary(ticket_id: int) -> Dict[str, Any]:
    """Delete the summary of a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/summary"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(url, headers=headers)
            if response.status_code == 204:
                return {"success": True, "message": "Ticket summary deleted successfully"}

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to delete ticket summary: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

def main():
    logging.info("Starting Freshdesk MCP server")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
