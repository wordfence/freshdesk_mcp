import httpx
from mcp.server.fastmcp import FastMCP
import logging
import os
import base64
from typing import Optional, Dict, Union, Any, List, Annotated
from enum import IntEnum, Enum
import re
from pydantic import BaseModel, Field
import json
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version

# Set up logging
logging.basicConfig(level=logging.INFO)

##
# Initialize FastMCP server
##
mcp = FastMCP("freshdesk-mcp")

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")

# Version info for health/UA
try:
    PACKAGE_VERSION = pkg_version("freshdesk-mcp")
except PackageNotFoundError:
    PACKAGE_VERSION = "dev"

USER_AGENT = f"freshdesk-mcp/{PACKAGE_VERSION}"

# Shared HTTP client (lazily initialized)
_client: Optional[httpx.AsyncClient] = None

def _auth_header_value() -> str:
    api_key = FRESHDESK_API_KEY or ""
    # Freshdesk basic auth uses api_key:X
    token = base64.b64encode(f"{api_key}:X".encode()).decode()
    return f"Basic {token}"

def _validate_env_or_raise() -> None:
    missing = []
    if not FRESHDESK_API_KEY:
        missing.append("FRESHDESK_API_KEY")
    if not FRESHDESK_DOMAIN:
        missing.append("FRESHDESK_DOMAIN")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    if "://" in FRESHDESK_DOMAIN:
        raise RuntimeError("FRESHDESK_DOMAIN should not include scheme; use e.g. 'yourcompany.freshdesk.com'")
    if "." not in FRESHDESK_DOMAIN:
        raise RuntimeError("FRESHDESK_DOMAIN looks invalid (no dot present)")

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        base_url = f"https://{FRESHDESK_DOMAIN}/api/v2"
        _client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": _auth_header_value(),
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
        )
    return _client

async def _request(method: str, url: str, *, params: Dict[str, Any] | None = None, json: Any | None = None, max_retries: int = 3) -> httpx.Response:
    """
    Thin wrapper with retry/backoff for transient errors and rate limiting.
    url may be relative (preferred; joined with base_url).
    """
    client = _get_client()
    attempt = 0
    backoff = 1.0
    last_exc: Optional[Exception] = None
    while attempt < max_retries:
        try:
            resp = await client.request(method, url, params=params, json=json)
            # Handle 429 and 5xx with backoff
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                retry_after = resp.headers.get("Retry-After")
                sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                await _async_sleep(sleep_s)
                attempt += 1
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            # Non-retriable status -> raise immediately
            last_exc = e
            break
        except httpx.RequestError as e:
            # Network error -> retry with backoff
            last_exc = e
            await _async_sleep(backoff)
            attempt += 1
            backoff *= 2
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed without exception (unexpected)")

async def _async_sleep(seconds: float) -> None:
    # Small helper to avoid importing asyncio at top‑level for tests that stub this.
    import asyncio
    await asyncio.sleep(seconds)

def _ok(
    data: Any,
    *,
    pagination: Optional[Dict[str, Any]] = None,
    warnings: Optional[List[str]] = None,
    next_call: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"success": True, "data": data}
    if pagination is not None:
        out["pagination"] = pagination
    if warnings:
        out["warnings"] = warnings
    if next_call is not None:
        out["next_call"] = next_call
    return out

def _err(err_type: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": False,
        "error": {
            "type": err_type,
            "message": message,
        }
    }
    if details:
        out["error"]["details"] = details
    return out

# --- Tool catalog for LLM selection ---
_TOOL_CATALOG: List[Dict[str, Any]] = [
    # Discovery
    {"name": "tools.list", "summary": "List available tools with summaries and docs.", "use_when": "You need an overview of tools.", "returns": "success, data: { tools }", "safety": "read", "keywords": ["discover", "catalog", "list"], "docs": "docs/tools.discovery.md"},
    {"name": "tools.search", "summary": "Search tools by name/keywords/summary.", "use_when": "Find the right tool by goal.", "returns": "success, data: { results }", "safety": "read", "keywords": ["discover", "search"], "docs": "docs/tools.discovery.md"},
    {"name": "tools.explain", "summary": "Return detailed documentation for a tool.", "use_when": "Need full usage details.", "returns": "success, data: { tool, doc }", "safety": "read", "keywords": ["docs", "explain"], "docs": "docs/tools.discovery.md"},
    {"name": "server.info", "summary": "Report MCP server version, readiness, and capabilities.", "use_when": "Health check or environment info.", "returns": "success, data: { name, version, freshdesk_domain, ready, capabilities }", "safety": "read", "keywords": ["health", "version"], "docs": "docs/tools.discovery.md"},

    # Tickets
    {"name": "tickets.create", "summary": "Create a ticket using subject, description, enums, and optional custom fields.", "use_when": "Starting a new support case.", "returns": "success, data: { ticket }", "safety": "write", "keywords": ["ticket", "create", "new"], "docs": "docs/tickets.create.md"},
    {"name": "tickets.update", "summary": "Update fields on an existing ticket (status, priority, assignee, custom_fields).", "use_when": "Modify existing tickets.", "returns": "success, data: { message, ticket }", "safety": "write", "keywords": ["ticket", "update", "status"], "docs": "docs/tickets.update.md"},
    {"name": "tickets.delete", "summary": "Delete a ticket by id.", "use_when": "Remove a mistaken or test ticket.", "returns": "success, data: { message }", "safety": "write", "keywords": ["ticket", "delete"], "docs": "docs/tickets.delete.md"},
    {"name": "tickets.get", "summary": "Fetch a single ticket by id.", "use_when": "Get ticket details.", "returns": "success, data: ticket", "safety": "read", "keywords": ["ticket", "view", "get"], "docs": "docs/tickets.get.md"},
    {"name": "tickets.list", "summary": "List tickets with pagination.", "use_when": "Browse tickets.", "returns": "success, data: { tickets, pagination }, next_call?", "safety": "read", "keywords": ["ticket", "list", "paginate"], "docs": "docs/tickets.list.md"},
    {"name": "tickets.search", "summary": "Search tickets using Freshdesk query syntax; optional HTML stripping.", "use_when": "Find tickets by criteria.", "returns": "success, data: { results }", "safety": "read", "keywords": ["ticket", "search", "query"], "docs": "docs/tickets.search.md"},
    {"name": "tickets.conversations.list", "summary": "List conversations across pages under a global token budget.", "use_when": "Read ticket history; receives summary, resume info, and pagination.", "returns": "success, data: { conversations, summary, resume }, pagination: { next_page, prev_page?, has_more }, next_call?", "safety": "read", "keywords": ["conversation", "replies", "paginate"], "docs": "docs/tickets.conversations.md"},
    {"name": "tickets.reply.create", "summary": "Add a public reply to a ticket.", "use_when": "Respond to requester.", "returns": "success, data: reply", "safety": "write", "keywords": ["reply", "message"], "docs": "docs/tickets.reply.md"},
    {"name": "tickets.note.create", "summary": "Add a private note to a ticket.", "use_when": "Internal note.", "returns": "success, data: note", "safety": "write", "keywords": ["note", "internal"], "docs": "docs/tickets.note.md"},
    {"name": "tickets.conversation.update", "summary": "Update a conversation body by conversation id.", "use_when": "Fix or amend a prior message.", "returns": "success, data: conversation", "safety": "write", "keywords": ["conversation", "update"], "docs": "docs/tickets.conversation.update.md"},
    {"name": "tickets.summary.get", "summary": "Get the summary of a ticket.", "use_when": "Read ticket summary.", "returns": "success, data: summary", "safety": "read", "keywords": ["summary"], "docs": "docs/tickets.summary.md"},
    {"name": "tickets.summary.update", "summary": "Update the summary of a ticket.", "use_when": "Modify ticket summary.", "returns": "success, data: summary", "safety": "write", "keywords": ["summary", "update"], "docs": "docs/tickets.summary.md"},
    {"name": "tickets.summary.delete", "summary": "Delete the summary of a ticket.", "use_when": "Remove ticket summary.", "returns": "success, data: { message }", "safety": "write", "keywords": ["summary", "delete"], "docs": "docs/tickets.summary.md"},

    # Fields
    {"name": "fields.tickets.list", "summary": "List all ticket fields and properties.", "use_when": "Build payloads with correct field keys.", "returns": "success, data: [fields]", "safety": "read", "keywords": ["fields", "ticket"], "docs": "docs/fields.tickets.md"},
    {"name": "fields.tickets.create", "summary": "Create a ticket field.", "use_when": "Administer ticket fields.", "returns": "success, data: field", "safety": "write", "keywords": ["fields", "ticket", "create"], "docs": "docs/fields.tickets.md"},
    {"name": "fields.tickets.get", "summary": "View a ticket field by id.", "use_when": "Inspect ticket field.", "returns": "success, data: field", "safety": "read", "keywords": ["fields", "ticket", "get"], "docs": "docs/fields.tickets.md"},
    {"name": "fields.tickets.update", "summary": "Update a ticket field by id.", "use_when": "Modify ticket field.", "returns": "success, data: field", "safety": "write", "keywords": ["fields", "ticket", "update"], "docs": "docs/fields.tickets.md"},
    {"name": "fields.tickets.get_property", "summary": "Get properties of a specific ticket field by name.", "use_when": "Find internal keys or constraints.", "returns": "success, data: field|None", "safety": "read", "keywords": ["fields", "ticket", "property"], "docs": "docs/fields.tickets.md"},
    {"name": "fields.contacts.list", "summary": "List contact fields.", "use_when": "Build contact payloads.", "returns": "success, data: [fields]", "safety": "read", "keywords": ["fields", "contacts"], "docs": "docs/contacts.fields.md"},
    {"name": "fields.contacts.get", "summary": "View a contact field.", "use_when": "Inspect contact field.", "returns": "success, data: field", "safety": "read", "keywords": ["fields", "contacts", "get"], "docs": "docs/contacts.fields.md"},
    {"name": "fields.contacts.create", "summary": "Create a contact field.", "use_when": "Administer contact fields.", "returns": "success, data: field", "safety": "write", "keywords": ["fields", "contacts", "create"], "docs": "docs/contacts.fields.md"},
    {"name": "fields.contacts.update", "summary": "Update a contact field.", "use_when": "Modify contact field.", "returns": "success, data: field", "safety": "write", "keywords": ["fields", "contacts", "update"], "docs": "docs/contacts.fields.md"},
    {"name": "fields.companies.list", "summary": "List company fields.", "use_when": "Build company payloads.", "returns": "success, data: [fields]", "safety": "read", "keywords": ["fields", "companies"], "docs": "docs/companies.fields.md"},

    # Contacts
    {"name": "contacts.list", "summary": "List contacts with pagination.", "use_when": "Browse contacts.", "returns": "success, data: { contacts, pagination }, next_call?", "safety": "read", "keywords": ["contacts", "list"], "docs": "docs/contacts.list.md"},
    {"name": "contacts.get", "summary": "Get a contact by id.", "use_when": "Read contact details.", "returns": "success, data: contact", "safety": "read", "keywords": ["contacts", "get"], "docs": "docs/contacts.get.md"},
    {"name": "contacts.search", "summary": "Autocomplete contacts by term.", "use_when": "Find a contact by name/email.", "returns": "success, data: [...]", "safety": "read", "keywords": ["contacts", "search"], "docs": "docs/contacts.search.md"},
    {"name": "contacts.update", "summary": "Update a contact by id.", "use_when": "Modify a contact.", "returns": "success, data: contact", "safety": "write", "keywords": ["contacts", "update"], "docs": "docs/contacts.update.md"},

    # Companies
    {"name": "companies.list", "summary": "List companies with pagination.", "use_when": "Browse companies.", "returns": "success, data: { companies, pagination }, next_call?", "safety": "read", "keywords": ["companies", "list"], "docs": "docs/companies.list.md"},
    {"name": "companies.get", "summary": "Get a company by id.", "use_when": "Read company details.", "returns": "success, data: company", "safety": "read", "keywords": ["companies", "get"], "docs": "docs/companies.get.md"},
    {"name": "companies.search", "summary": "Autocomplete companies by name.", "use_when": "Find a company.", "returns": "success, data: [...]", "safety": "read", "keywords": ["companies", "search"], "docs": "docs/companies.search.md"},
    {"name": "companies.find_by_name", "summary": "Find a company by name.", "use_when": "Find a specific company.", "returns": "success, data: [...]", "safety": "read", "keywords": ["companies", "find"], "docs": "docs/companies.search.md"},

    # Agents
    {"name": "agents.list", "summary": "List agents with pagination.", "use_when": "Browse agents.", "returns": "success, data: { agents, pagination }, next_call?", "safety": "read", "keywords": ["agents", "list"], "docs": "docs/agents.list.md"},
    {"name": "agents.get", "summary": "Get an agent by id.", "use_when": "Read agent details.", "returns": "success, data: agent", "safety": "read", "keywords": ["agents", "get"], "docs": "docs/agents.get.md"},
    {"name": "agents.search", "summary": "Autocomplete agents by term.", "use_when": "Find an agent.", "returns": "success, data: [...]", "safety": "read", "keywords": ["agents", "search"], "docs": "docs/agents.search.md"},
    {"name": "agents.create", "summary": "Create a new agent.", "use_when": "Provision an agent.", "returns": "success, data: agent", "safety": "write", "keywords": ["agents", "create"], "docs": "docs/agents.create.md"},
    {"name": "agents.update", "summary": "Update an agent by id.", "use_when": "Modify agent.", "returns": "success, data: agent", "safety": "write", "keywords": ["agents", "update"], "docs": "docs/agents.update.md"},

    # Groups
    {"name": "groups.list", "summary": "List groups with pagination.", "use_when": "Browse groups.", "returns": "success, data: { groups, pagination }, next_call?", "safety": "read", "keywords": ["groups", "list"], "docs": "docs/groups.list.md"},
    {"name": "groups.get", "summary": "Get a group by id.", "use_when": "Read group details.", "returns": "success, data: group", "safety": "read", "keywords": ["groups", "get"], "docs": "docs/groups.get.md"},
    {"name": "groups.create", "summary": "Create a group.", "use_when": "Provision a group.", "returns": "success, data: group", "safety": "write", "keywords": ["groups", "create"], "docs": "docs/groups.create.md"},
    {"name": "groups.update", "summary": "Update a group.", "use_when": "Modify group.", "returns": "success, data: group", "safety": "write", "keywords": ["groups", "update"], "docs": "docs/groups.update.md"},

    # Canned responses
    {"name": "canned.folders.list", "summary": "List canned response folders.", "use_when": "Browse folders.", "returns": "success, data: { folders }", "safety": "read", "keywords": ["canned", "folders", "list"], "docs": "docs/canned.folders.list.md"},
    {"name": "canned.folders.create", "summary": "Create a canned response folder.", "use_when": "Create folder.", "returns": "success, data: folder", "safety": "write", "keywords": ["canned", "folders", "create"], "docs": "docs/canned.folders.create.md"},
    {"name": "canned.folders.update", "summary": "Update a canned response folder.", "use_when": "Rename/update folder.", "returns": "success, data: folder", "safety": "write", "keywords": ["canned", "folders", "update"], "docs": "docs/canned.folders.update.md"},
    {"name": "canned.list", "summary": "List canned responses in a folder.", "use_when": "Browse canned responses.", "returns": "success, data: { canned_responses }", "safety": "read", "keywords": ["canned", "list"], "docs": "docs/canned.list.md"},
    {"name": "canned.get", "summary": "Get a canned response by id.", "use_when": "Read canned response.", "returns": "success, data: canned_response", "safety": "read", "keywords": ["canned", "get"], "docs": "docs/canned.get.md"},
    {"name": "canned.create", "summary": "Create a canned response.", "use_when": "Add canned response.", "returns": "success, data: canned_response", "safety": "write", "keywords": ["canned", "create"], "docs": "docs/canned.create.md"},
    {"name": "canned.update", "summary": "Update a canned response.", "use_when": "Modify canned response.", "returns": "success, data: canned_response", "safety": "write", "keywords": ["canned", "update"], "docs": "docs/canned.update.md"},

    # Solutions (KB)
    {"name": "solutions.categories.list", "summary": "List solution categories.", "use_when": "Browse categories.", "returns": "success, data: { categories }", "safety": "read", "keywords": ["solutions", "categories", "list"], "docs": "docs/solutions.categories.list.md"},
    {"name": "solutions.categories.get", "summary": "Get a solution category by id.", "use_when": "Read category.", "returns": "success, data: category", "safety": "read", "keywords": ["solutions", "categories", "get"], "docs": "docs/solutions.categories.get.md"},
    {"name": "solutions.categories.create", "summary": "Create a solution category.", "use_when": "Add category.", "returns": "success, data: category", "safety": "write", "keywords": ["solutions", "categories", "create"], "docs": "docs/solutions.categories.create.md"},
    {"name": "solutions.categories.update", "summary": "Update a solution category.", "use_when": "Modify category.", "returns": "success, data: category", "safety": "write", "keywords": ["solutions", "categories", "update"], "docs": "docs/solutions.categories.update.md"},
    {"name": "solutions.folders.list", "summary": "List solution folders in a category.", "use_when": "Browse folders.", "returns": "success, data: { folders }", "safety": "read", "keywords": ["solutions", "folders", "list"], "docs": "docs/solutions.folders.list.md"},
    {"name": "solutions.folders.get", "summary": "Get a solution folder by id.", "use_when": "Read folder.", "returns": "success, data: folder", "safety": "read", "keywords": ["solutions", "folders", "get"], "docs": "docs/solutions.folders.get.md"},
    {"name": "solutions.folders.create", "summary": "Create a solution folder in a category.", "use_when": "Add folder.", "returns": "success, data: folder", "safety": "write", "keywords": ["solutions", "folders", "create"], "docs": "docs/solutions.folders.create.md"},
    {"name": "solutions.folders.update", "summary": "Update a solution folder by id.", "use_when": "Modify folder.", "returns": "success, data: folder", "safety": "write", "keywords": ["solutions", "folders", "update"], "docs": "docs/solutions.folders.update.md"},
    {"name": "solutions.articles.list", "summary": "List solution articles in a folder.", "use_when": "Browse articles.", "returns": "success, data: { articles }", "safety": "read", "keywords": ["solutions", "articles", "list"], "docs": "docs/solutions.articles.list.md"},
    {"name": "solutions.articles.get", "summary": "Get a solution article by id.", "use_when": "Read article.", "returns": "success, data: article", "safety": "read", "keywords": ["solutions", "articles", "get"], "docs": "docs/solutions.articles.get.md"},
    {"name": "solutions.articles.create", "summary": "Create a solution article in a folder.", "use_when": "Add article.", "returns": "success, data: article", "safety": "write", "keywords": ["solutions", "articles", "create"], "docs": "docs/solutions.articles.create.md"},
    {"name": "solutions.articles.update", "summary": "Update a solution article by id.", "use_when": "Modify article.", "returns": "success, data: article", "safety": "write", "keywords": ["solutions", "articles", "update"], "docs": "docs/solutions.articles.update.md"},
]

def _catalog_search(query: str) -> List[Dict[str, Any]]:
    q = query.lower()
    scored = []
    for item in _TOOL_CATALOG:
        hay = " ".join([
            item.get("name", ""),
            item.get("summary", ""),
            " ".join(item.get("keywords", [])),
        ]).lower()
        score = 0
        if item["name"].lower() == q:
            score += 5
        if q in hay:
            score += 2
        # simple token overlap
        overlap = sum(1 for tok in q.split() if tok in hay)
        score += overlap
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [i for _, i in scored]

@mcp.tool("tools.list")
async def tools_list() -> Dict[str, Any]:
    """List available tools with concise summaries for LLM selection."""
    return _ok({"tools": _TOOL_CATALOG})

@mcp.tool("tools.search")
async def tools_search(query: str, limit: Annotated[int, Field(ge=1, le=20, description="Max results")] = 5) -> Dict[str, Any]:
    """Search tools by name/keywords/summary and return top matches."""
    hits = _catalog_search(query)[:limit]
    return _ok({"query": query, "results": hits})

@mcp.tool("tools.explain")
async def tools_explain(name: str) -> Dict[str, Any]:
    """Return detailed documentation for a tool, including params and references."""
    match = next((t for t in _TOOL_CATALOG if t["name"] == name), None)
    if not match:
        return _err("not_found", f"No tool named '{name}'")
    # Try to read local docs file if present
    docs_path = match.get("docs")
    body: Optional[str] = None
    if docs_path:
        try:
            with open(docs_path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception:
            body = None
    return _ok({"tool": match, "doc": body})


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


def strip_html_tags(html: str) -> str:
    """Remove HTML tags and return readable text.

    - Converts basic block/line-break tags to newlines for readability.
    - Leaves plain strings untouched for performance.
    """
    if not isinstance(html, str) or '<' not in html or '>' not in html:
        return html

    from html.parser import HTMLParser
    from html import unescape

    block_tags = {
        'p', 'div', 'section', 'article', 'header', 'footer', 'li', 'ul', 'ol',
        'table', 'tr', 'td', 'th', 'thead', 'tbody', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
    }

    class Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: List[str] = []

        def handle_starttag(self, tag, attrs):
            t = tag.lower()
            if t in ('br',):
                self.parts.append('\n')

        def handle_startendtag(self, tag, attrs):
            t = tag.lower()
            if t in ('br', 'hr'):
                self.parts.append('\n')

        def handle_data(self, data):
            if data:
                self.parts.append(data)

        def handle_endtag(self, tag):
            t = tag.lower()
            if t in block_tags:
                self.parts.append('\n')

    parser = Stripper()
    try:
        parser.feed(html)
    except Exception:
        # In case of malformed HTML, fall back to a naive strip
        import re
        return unescape(re.sub(r'<[^>]+>', '', html))

    text = ''.join(parser.parts)

    # Unescape HTML entities and normalize whitespace
    text = unescape(text)
    # Collapse more than 2 newlines to max 2, and trim whitespace around lines
    lines = [ln.strip() for ln in text.splitlines()]
    collapsed = []
    empty_streak = 0
    for ln in lines:
        if ln == '':
            empty_streak += 1
            if empty_streak <= 2:
                collapsed.append('')
        else:
            empty_streak = 0
            collapsed.append(ln)
    return '\n'.join(collapsed).strip()


def _strip_html_from_obj(obj: Any) -> Any:
    """Recursively strip HTML tags from strings within dict/list structures."""
    if isinstance(obj, str):
        return strip_html_tags(obj)
    if isinstance(obj, list):
        return [_strip_html_from_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_html_from_obj(v) for k, v in obj.items()}
    return obj


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

@mcp.tool("fields.tickets.list")
async def fields_tickets_list() -> Dict[str, Any]:
    """Get ticket fields from Freshdesk."""
    try:
        resp = await _request("GET", "/ticket_fields")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch ticket fields", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("server.info")
async def get_server_info() -> Dict[str, Any]:
    """
    Health/version endpoint for clients and operators.
    Reports readiness and basic configuration metadata (non-secret).
    """
    ready = bool(FRESHDESK_API_KEY and FRESHDESK_DOMAIN)
    return _ok({
        "name": "freshdesk-mcp",
        "version": PACKAGE_VERSION,
        "freshdesk_domain": FRESHDESK_DOMAIN,
        "ready": ready,
        "capabilities": {
            "pagination": True,
            "token_budgeting": True,
            "html_processing": True,
            "retries": True,
        }
    })


@mcp.tool("tickets.list")
async def tickets_list(
    page: Annotated[int, Field(ge=1, description="Page number")] = 1,
    per_page: Annotated[int, Field(ge=1, le=100, description="Items per page")] = 30,
) -> Dict[str, Any]:
    """Get tickets from Freshdesk with pagination support."""
    params = {"page": page, "per_page": per_page}
    try:
        response = await _request("GET", "/tickets", params=params)
        link_header = response.headers.get("Link", "")
        pagination_info = parse_link_header(link_header)
        tickets = response.json()
        next_page = pagination_info.get("next")
        return _ok({"tickets": tickets}, pagination={
            "current_page": page,
            "next_page": next_page,
            "prev_page": pagination_info.get("prev"),
            "per_page": per_page,
        }, next_call=(
            {"tool": "tickets.list", "arguments": {"page": next_page, "per_page": per_page}}
            if next_page is not None else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch tickets", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("tickets.create")
async def tickets_create(
    subject: str,
    description: str,
    source: TicketSource,
    priority: TicketPriority,
    status: TicketStatus,
    email: Optional[str] = None,
    requester_id: Optional[int] = None,
    custom_fields: Optional[Dict[str, Any]] = None,
    additional_fields: Optional[Dict[str, Any]] = None  # 👈 new parameter
) -> str:
    """Create a ticket in Freshdesk"""
    # Validate requester information
    if not email and not requester_id:
        return "Error: Either email or requester_id must be provided"

    # Prepare the request data
    data = {
        "subject": subject,
        "description": description,
        "source": int(source),
        "priority": int(priority),
        "status": int(status)
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

    try:
        response = await _request("POST", "/tickets", json=data)
        if response.status_code == 201:
            return "Ticket created successfully"
        response_data = response.json()
        return f"Success: {response_data}"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            try:
                error_data = e.response.json()
                if "errors" in error_data:
                    return f"Validation Error: {error_data['errors']}"
            except Exception:
                pass
        return f"Error: Failed to create ticket - {str(e)}"
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

@mcp.tool("tickets.update")
async def tickets_update(ticket_id: int, ticket_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a ticket in Freshdesk."""
    if not ticket_fields:
        return _err("validation_error", "No fields provided for update")

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

    try:
        response = await _request("PUT", f"/tickets/{ticket_id}", json=update_data)
        return _ok({
            "message": "Ticket updated successfully",
            "ticket": response.json()
        })
    except httpx.HTTPStatusError as e:
        details = None
        try:
            details = e.response.json()
        except Exception:
            pass
        # surface validation errors if present
        if isinstance(details, dict) and "errors" in details:
            return _err("validation_error", "Validation errors while updating ticket", details={"errors": details["errors"], "status": e.response.status_code})
        return _err("http_error", "Failed to update ticket", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("tickets.delete")
async def tickets_delete(ticket_id: int) -> Dict[str, Any]:
    """Delete a ticket in Freshdesk."""
    try:
        resp = await _request("DELETE", f"/tickets/{ticket_id}")
        if resp.status_code == 204:
            return _ok({"message": "Ticket deleted"})
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to delete ticket", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.get")
async def tickets_get(ticket_id: int) -> Dict[str, Any]:
    """Get a ticket in Freshdesk."""
    try:
        resp = await _request("GET", f"/tickets/{ticket_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch ticket", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.search")
async def tickets_search(
    query: str,
    quantity: Optional[int] = None,
    strip_html: Optional[bool] = True,
) -> Dict[str, Any]:
    """Search for tickets in Freshdesk.

    Notes:
    - Freshdesk expects the entire query value to be wrapped in double quotes.
      When specifying via JSON/MCP, escape the quotes. Examples:
        query="\"status:2\"" or query="\"(status:2 AND priority:1)\"".
    - If strip_html is True, removes HTML tags from each item in the response's
      "results" array for cleaner, token‑efficient output.
    """
    params = {"query": query}
    try:
        response = await _request("GET", "/search/tickets", params=params)
        data = response.json()

    # Clean up HTML tags in results, if present
        if strip_html and isinstance(data, dict) and isinstance(data.get("results"), list):
            cleaned = [_strip_html_from_obj(item) for item in data["results"]]
            data["results"] = cleaned
        if quantity is not None and isinstance(data, dict) and isinstance(data.get("results"), list):
            return _ok(data["results"][:quantity])
        return _ok(data)
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to search tickets", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("tickets.conversations.list")
async def tickets_conversations_list(
    ticket_id: int,
    page: Annotated[int, Field(ge=1, description="Starting page number")] = 1,
    per_page: Annotated[int, Field(ge=1, le=100, description="Conversations per page")] = 10,
    filter_encrypted_reports: Optional[bool] = True,
    report_placeholder: Optional[str] = "[ENCRYPTED REPORT REMOVED]",
    max_tokens: Annotated[int, Field(ge=1, le=20000, description="Global token budget across pages")] = 20000,
    include_html_body: Optional[bool] = False,
    extract_links: Optional[bool] = True,
) -> Dict[str, Any]:
    """List ticket conversations across multiple pages under a global token budget.

    This function fetches successive pages starting from `page`, using a constant `per_page`,
    until either the global token budget (`max_tokens`) is reached or no more pages are available.
    Client paging: while `pagination.has_more` (or `resume.has_more`) is true, call this tool
    again with `page = pagination.next_page` and the same `per_page` until `next_page` is null.

    Parameters
    - ticket_id: The ID of the ticket
    - page: Starting page number (>=1)
    - per_page: Conversations per page (1–100), constant during the run
    - filter_encrypted_reports: Remove blocks between BEGIN/END REPORT tags
    - report_placeholder: Placeholder used when filtering encrypted blocks
    - max_tokens: Global token budget across pages (1–20000)
    - include_html_body: Include raw HTML body (default false)
    - extract_links: Extract anchor links into a `links` array

    Returns
    - success, data: { conversations, summary, filtering?, resume }, warnings?, pagination, next_call?
      - summary: { total_conversations, total_pages_fetched, total_token_count, complete }
      - resume: {
          has_more: bool,
          exhausted_token_budget: bool,
          next_page: int | null,
          last_conversation_id: int | null
        }
      - pagination: { has_more: bool, next_page: int|null, prev_page?: int|null }
      - next_call: If more data remains, a convenience hint:
          { tool: "tickets.conversations.list", arguments: { ticket_id, page, per_page } }

    Resume guidance
    - CRITICAL: NEVER change `per_page` between successive calls in the same
      paging session. Changing it will misalign pages and can cause skipped or
      duplicated conversations. Always reuse the exact `per_page` value you
      started with. If you must change it, restart from page 1 or rebuild a
      client-side seen‑ID set and re-fetch overlapping pages.
    - When resuming on `resume.next_page`, scan that page's conversations to find
      the item whose `id == resume.last_conversation_id` and only process the
      items that appear AFTER that anchor in the page's returned order. If the
      anchor is not found (content changed), process all items on the page.
    - For extra safety against reordering or merges, maintain a client-side set
      of seen conversation IDs and skip already-processed IDs.
    """
    # Validate input parameters
    if page < 1:
        return _err("validation_error", "Page number must be greater than 0")
    
    if per_page < 1 or per_page > 100:
        return _err("validation_error", "Page size must be between 1 and 100")
    
    if max_tokens > 20000:
        return _err("validation_error", "Maximum tokens cannot exceed 20000")
    
    # Multi-page loop with constant per_page
    try:
        all_conversations: List[Dict[str, Any]] = []
        total_tokens = 0
        reports_found_total = 0
        tokens_saved_total = 0
        current_page = page
        has_more = True
        last_conversation_id: Optional[int] = None

        while has_more and total_tokens < max_tokens:
            params = {"page": current_page, "per_page": per_page}
            response = await _request("GET", f"/tickets/{ticket_id}/conversations", params=params)
            link_header = response.headers.get('Link', '')
            pagination_info = parse_link_header(link_header)
            conversations = response.json()

            # Process each conversation, respecting the remaining token budget
            for conv in conversations:
                processed_conv = process_conversation_body(
                    conv,
                    filter_reports=filter_encrypted_reports,
                    report_placeholder=report_placeholder
                )

                # Update filtering stats and tokens saved
                for field in ['body', 'body_text', 'description']:
                    if field in conv and conv[field] and "-----BEGIN REPORT-----" in conv[field]:
                        reports_found_total += 1
                        original_tokens = estimate_tokens(conv[field])
                        filtered_tokens = estimate_tokens(processed_conv.get(field, ""))
                        tokens_saved_total += (original_tokens - filtered_tokens)

                # Optionally extract links from HTML body
                if extract_links and 'body' in processed_conv and processed_conv['body']:
                    links = extract_links_from_html(processed_conv['body'])
                    if links:
                        processed_conv['links'] = links

                # Optionally remove HTML body
                if not include_html_body and 'body' in processed_conv:
                    processed_conv.pop('body', None)

                conv_json = json.dumps(processed_conv)
                conv_tokens = estimate_tokens(conv_json)
                if total_tokens + conv_tokens > max_tokens:
                    # Stop within this page; return resume info pointing to this same page
                    has_more = True
                    next_page = current_page
                    warnings: List[str] = [f"Stopped due to token budget. Resume from page {next_page}."]
                    return _ok({
                        "conversations": all_conversations,
                        "summary": {
                            "total_conversations": len(all_conversations),
                            "total_pages_fetched": max(0, current_page - page),
                            "total_token_count": total_tokens,
                            "complete": False,
                        },
                        "resume": {
                            "has_more": has_more,
                            "exhausted_token_budget": True,
                            "next_page": next_page,
                            "last_conversation_id": last_conversation_id,
                        },
                        "filtering": {
                            "encrypted_reports_removed": bool(filter_encrypted_reports),
                            "total_reports_found": reports_found_total,
                            "total_tokens_saved": tokens_saved_total,
                        }
                    }, pagination={
                        "has_more": True,
                        "next_page": next_page,
                        "prev_page": pagination_info.get("prev"),
                    }, warnings=warnings, next_call={
                        "tool": "tickets.conversations.list",
                        "arguments": {
                            "ticket_id": ticket_id,
                            "page": next_page,
                            "per_page": per_page,
                        }
                    })

                all_conversations.append(processed_conv)
                total_tokens += conv_tokens
                # Track last conversation id if present
                try:
                    last_conversation_id = int(conv.get("id")) if isinstance(conv.get("id"), (int, str)) else last_conversation_id
                except Exception:
                    pass

            # Finished this page without hitting budget
            next_page_val = pagination_info.get("next")
            has_more = next_page_val is not None
            if has_more:
                current_page = next_page_val

        # Completed all pages or budget exactly used at page boundary
        return _ok({
            "conversations": all_conversations,
            "summary": {
                "total_conversations": len(all_conversations),
                "total_pages_fetched": max(0, current_page - page),
                "total_token_count": total_tokens,
                "complete": not has_more,
            },
            "resume": {
                "has_more": has_more,
                "exhausted_token_budget": False,
                "next_page": current_page if has_more else None,
                "last_conversation_id": last_conversation_id,
            },
            "filtering": {
                "encrypted_reports_removed": bool(filter_encrypted_reports),
                "total_reports_found": reports_found_total,
                "total_tokens_saved": tokens_saved_total,
            }
        }, pagination={
            "has_more": has_more,
            "next_page": current_page if has_more else None,
            # prev_page is not strictly required for forward paging; can be derived by clients
        }, next_call=(
            {"tool": "tickets.conversations.list", "arguments": {"ticket_id": ticket_id, "page": current_page, "per_page": per_page}}
            if has_more else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch conversations", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

# removed tickets.conversations.list_all; use tickets.conversations.list with auto_paginate=true


@mcp.tool("tickets.reply.create")
async def tickets_reply_create(ticket_id: int,body: str)-> Dict[str, Any]:
    """Create a reply to a ticket in Freshdesk."""
    data = {"body": body}
    try:
        resp = await _request("POST", f"/tickets/{ticket_id}/reply", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create ticket reply", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.note.create")
async def tickets_note_create(ticket_id: int,body: str)-> Dict[str, Any]:
    """Create a note for a ticket in Freshdesk."""
    data = {"body": body}
    try:
        resp = await _request("POST", f"/tickets/{ticket_id}/notes", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create ticket note", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.conversation.update")
async def tickets_conversation_update(conversation_id: int,body: str)-> Dict[str, Any]:
    """Update a conversation for a ticket in Freshdesk."""
    data = {"body": body}
    try:
        resp = await _request("PUT", f"/conversations/{conversation_id}", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update conversation", details={"status": e.response.status_code, "conversation_id": conversation_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"conversation_id": conversation_id})

@mcp.tool("agents.list")
async def agents_list(
    page: Annotated[int, Field(ge=1, description="Page number")] = 1,
    per_page: Annotated[int, Field(ge=1, le=100, description="Items per page")] = 30
) -> Dict[str, Any]:
    """Get all agents in Freshdesk with pagination support."""
    params = {"page": page, "per_page": per_page}
    try:
        resp = await _request("GET", "/agents", params=params)
        link_header = resp.headers.get("Link", "")
        pagination_info = parse_link_header(link_header)
        next_page = pagination_info.get("next")
        return _ok({"agents": resp.json()}, pagination={
            "current_page": page,
            "next_page": next_page,
            "prev_page": pagination_info.get("prev"),
            "per_page": per_page,
        }, next_call=(
            {"tool": "agents.list", "arguments": {"page": next_page, "per_page": per_page}}
            if next_page is not None else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch agents", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("contacts.list")
async def contacts_list(
    page: Annotated[int, Field(ge=1, description="Page number")] = 1,
    per_page: Annotated[int, Field(ge=1, le=100, description="Items per page")] = 30
) -> Dict[str, Any]:
    """List all contacts in Freshdesk with pagination support."""
    params = {"page": page, "per_page": per_page}
    try:
        resp = await _request("GET", "/contacts", params=params)
        link_header = resp.headers.get("Link", "")
        pagination_info = parse_link_header(link_header)
        next_page = pagination_info.get("next")
        return _ok({"contacts": resp.json()}, pagination={
            "current_page": page,
            "next_page": next_page,
            "prev_page": pagination_info.get("prev"),
            "per_page": per_page,
        }, next_call=(
            {"tool": "contacts.list", "arguments": {"page": next_page, "per_page": per_page}}
            if next_page is not None else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch contacts", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("contacts.get")
async def contacts_get(contact_id: int)-> Dict[str, Any]:
    """Get a contact in Freshdesk."""
    try:
        resp = await _request("GET", f"/contacts/{contact_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch contact", details={"status": e.response.status_code, "contact_id": contact_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"contact_id": contact_id})

@mcp.tool("contacts.search")
async def contacts_search(query: str)-> Dict[str, Any]:
    """Search for contacts in Freshdesk."""
    params = {"term": query}
    try:
        resp = await _request("GET", "/contacts/autocomplete", params=params)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to search contacts", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("contacts.update")
async def contacts_update(contact_id: int, contact_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a contact in Freshdesk."""
    data = {k: v for k, v in contact_fields.items()}
    try:
        resp = await _request("PUT", f"/contacts/{contact_id}", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update contact", details={"status": e.response.status_code, "contact_id": contact_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"contact_id": contact_id})
@mcp.tool("canned.list")
async def canned_list(folder_id: int)-> Dict[str, Any]:
    """List all canned responses in Freshdesk."""
    try:
        resp = await _request("GET", f"/canned_response_folders/{folder_id}/responses")
        return _ok({"canned_responses": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list canned responses", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"folder_id": folder_id})

@mcp.tool("canned.folders.list")
async def canned_folders_list()-> Dict[str, Any]:
    """List all canned response folders in Freshdesk."""
    try:
        resp = await _request("GET", "/canned_response_folders")
        return _ok({"folders": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list canned response folders", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("canned.get")
async def canned_get(canned_response_id: int)-> Dict[str, Any]:
    """View a canned response in Freshdesk."""
    try:
        resp = await _request("GET", f"/canned_responses/{canned_response_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view canned response", details={"status": e.response.status_code, "canned_response_id": canned_response_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("canned.create")
async def canned_create(canned_response_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a canned response in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = CannedResponseCreate(**canned_response_fields)
        # Convert to dict for API request
        canned_response_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return _err("validation_error", f"Validation error: {str(e)}")

    try:
        resp = await _request("POST", "/canned_responses", json=canned_response_data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create canned response", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("canned.update")
async def canned_update(canned_response_id: int, canned_response_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a canned response in Freshdesk."""
    try:
        resp = await _request("PUT", f"/canned_responses/{canned_response_id}", json=canned_response_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update canned response", details={"status": e.response.status_code, "canned_response_id": canned_response_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("canned.folders.create")
async def canned_folders_create(name: str)-> Dict[str, Any]:
    """Create a canned response folder in Freshdesk."""
    data = {"name": name}
    try:
        resp = await _request("POST", "/canned_response_folders", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create canned response folder", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("canned.folders.update")
async def canned_folders_update(folder_id: int, name: str)-> Dict[str, Any]:
    """Update a canned response folder in Freshdesk."""
    data = {"name": name}
    try:
        resp = await _request("PUT", f"/canned_response_folders/{folder_id}", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update canned response folder", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.articles.list")
async def list_solution_articles(folder_id: int)-> Dict[str, Any]:
    """List all solution articles in Freshdesk."""
    try:
        resp = await _request("GET", f"/solutions/folders/{folder_id}/articles")
        return _ok({"articles": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list solution articles", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.folders.list")
async def list_solution_folders(category_id: int)-> Dict[str, Any]:
    if not category_id:
        return _err("validation_error", "Category ID is required")
    """List all solution folders in Freshdesk."""
    try:
        resp = await _request("GET", f"/solutions/categories/{category_id}/folders")
        return _ok({"folders": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list solution folders", details={"status": e.response.status_code, "category_id": category_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.categories.list")
async def list_solution_categories()-> Dict[str, Any]:
    """List all solution categories in Freshdesk."""
    try:
        resp = await _request("GET", "/solutions/categories")
        return _ok({"categories": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list solution categories", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.categories.get")
async def view_solution_category(category_id: int)-> Dict[str, Any]:
    """View a solution category in Freshdesk."""
    try:
        resp = await _request("GET", f"/solutions/categories/{category_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view solution category", details={"status": e.response.status_code, "category_id": category_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.categories.create")
async def create_solution_category(category_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution category in Freshdesk."""
    if not category_fields.get("name"):
        return _err("validation_error", "Name is required")

    try:
        resp = await _request("POST", "/solutions/categories", json=category_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create solution category", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.categories.update")
async def update_solution_category(category_id: int, category_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution category in Freshdesk."""
    if not category_fields.get("name"):
        return _err("validation_error", "Name is required")

    try:
        resp = await _request("PUT", f"/solutions/categories/{category_id}", json=category_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update solution category", details={"status": e.response.status_code, "category_id": category_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.folders.create")
async def create_solution_category_folder(category_id: int, folder_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution category folder in Freshdesk."""
    if not folder_fields.get("name"):
        return _err("validation_error", "Name is required")
    try:
        resp = await _request("POST", f"/solutions/categories/{category_id}/folders", json=folder_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create solution folder", details={"status": e.response.status_code, "category_id": category_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.folders.get")
async def view_solution_category_folder(folder_id: int)-> Dict[str, Any]:
    """View a solution category folder in Freshdesk."""
    try:
        resp = await _request("GET", f"/solutions/folders/{folder_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view solution folder", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("solutions.folders.update")
async def update_solution_category_folder(folder_id: int, folder_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution category folder in Freshdesk."""
    if not folder_fields.get("name"):
        return _err("validation_error", "Name is required")
    try:
        resp = await _request("PUT", f"/solutions/folders/{folder_id}", json=folder_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update solution folder", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")


@mcp.tool("solutions.articles.create")
async def create_solution_article(folder_id: int, article_fields: Dict[str, Any])-> Dict[str, Any]:
    """Create a solution article in Freshdesk."""
    if not article_fields.get("title") or not article_fields.get("status") or not article_fields.get("description"):
        return _err("validation_error", "Title, status and description are required")
    try:
        resp = await _request("POST", f"/solutions/folders/{folder_id}/articles", json=article_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create solution article", details={"status": e.response.status_code, "folder_id": folder_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.articles.get")
async def view_solution_article(article_id: int)-> Dict[str, Any]:
    """View a solution article in Freshdesk."""
    try:
        resp = await _request("GET", f"/solutions/articles/{article_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view solution article", details={"status": e.response.status_code, "article_id": article_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("solutions.articles.update")
async def update_solution_article(article_id: int, article_fields: Dict[str, Any])-> Dict[str, Any]:
    """Update a solution article in Freshdesk."""
    try:
        resp = await _request("PUT", f"/solutions/articles/{article_id}", json=article_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update solution article", details={"status": e.response.status_code, "article_id": article_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("agents.get")
async def view_agent(agent_id: int)-> Dict[str, Any]:
    """View an agent in Freshdesk."""
    try:
        resp = await _request("GET", f"/agents/{agent_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view agent", details={"status": e.response.status_code, "agent_id": agent_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("agents.create")
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

    try:
        response = await _request("POST", "/agents", json=agent_fields)
        return _ok(response.json())
    except httpx.HTTPStatusError as e:
        details = None
        try:
            details = e.response.json()
        except Exception:
            pass
        return _err("http_error", "Failed to create agent", details={"status": e.response.status_code, "details": details})

@mcp.tool("agents.update")
async def update_agent(agent_id: int, agent_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an agent in Freshdesk."""
    try:
        resp = await _request("PUT", f"/agents/{agent_id}", json=agent_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update agent", details={"status": e.response.status_code, "agent_id": agent_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("agents.search")
async def search_agents(query: str) -> Dict[str, Any]:
    """Search for agents in Freshdesk."""
    params = {"term": query}
    try:
        resp = await _request("GET", "/agents/autocomplete", params=params)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to search agents", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("groups.list")
async def list_groups(page: Annotated[int, Field(ge=1, description="Page number")] = 1, per_page: Annotated[int, Field(ge=1, le=100, description="Items per page")] = 30)-> Dict[str, Any]:
    """List all groups in Freshdesk."""
    params = {"page": page, "per_page": per_page}
    try:
        resp = await _request("GET", "/groups", params=params)
        link_header = resp.headers.get("Link", "")
        pagination_info = parse_link_header(link_header)
        next_page = pagination_info.get("next")
        return _ok({"groups": resp.json()}, pagination={
            "current_page": page,
            "next_page": next_page,
            "prev_page": pagination_info.get("prev"),
            "per_page": per_page,
        }, next_call=(
            {"tool": "groups.list", "arguments": {"page": next_page, "per_page": per_page}}
            if next_page is not None else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list groups", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("groups.create")
async def create_group(group_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a group in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = GroupCreate(**group_fields)
        # Convert to dict for API request
        group_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return _err("validation_error", f"Validation error: {str(e)}")

    try:
        response = await _request("POST", "/groups", json=group_data)
        return _ok(response.json())
    except httpx.HTTPStatusError as e:
        details = None
        try:
            details = e.response.json()
        except Exception:
            pass
        return _err("http_error", "Failed to create group", details={"status": e.response.status_code, "details": details})

@mcp.tool("groups.get")
async def view_group(group_id: int) -> Dict[str, Any]:
    """View a group in Freshdesk."""
    try:
        resp = await _request("GET", f"/groups/{group_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view group", details={"status": e.response.status_code, "group_id": group_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.tickets.create")
async def create_ticket_field(ticket_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a ticket field in Freshdesk."""
    try:
        resp = await _request("POST", "/admin/ticket_fields", json=ticket_field_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create ticket field", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("fields.tickets.get")
async def view_ticket_field(ticket_field_id: int) -> Dict[str, Any]:
    """View a ticket field in Freshdesk."""
    try:
        resp = await _request("GET", f"/admin/ticket_fields/{ticket_field_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view ticket field", details={"status": e.response.status_code, "ticket_field_id": ticket_field_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.tickets.update")
async def update_ticket_field(ticket_field_id: int, ticket_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a ticket field in Freshdesk."""
    try:
        resp = await _request("PUT", f"/admin/ticket_fields/{ticket_field_id}", json=ticket_field_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update ticket field", details={"status": e.response.status_code, "ticket_field_id": ticket_field_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("groups.update")
async def update_group(group_id: int, group_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a group in Freshdesk."""
    try:
        validated_fields = GroupCreate(**group_fields)
        # Convert to dict for API request
        group_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return _err("validation_error", f"Validation error: {str(e)}")
    try:
        response = await _request("PUT", f"/groups/{group_id}", json=group_data)
        return _ok(response.json())
    except httpx.HTTPStatusError as e:
        details = None
        try:
            details = e.response.json()
        except Exception:
            pass
        return _err("http_error", "Failed to update group", details={"status": e.response.status_code, "details": details})

@mcp.tool("fields.contacts.list")
async def list_contact_fields()-> Dict[str, Any]:
    """List all contact fields in Freshdesk."""
    try:
        resp = await _request("GET", "/contact_fields")
        return _ok({"contact_fields": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to list contact fields", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.contacts.get")
async def view_contact_field(contact_field_id: int) -> Dict[str, Any]:
    """View a contact field in Freshdesk."""
    try:
        resp = await _request("GET", f"/contact_fields/{contact_field_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to view contact field", details={"status": e.response.status_code, "contact_field_id": contact_field_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.contacts.create")
async def create_contact_field(contact_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a contact field in Freshdesk."""
    # Validate input using Pydantic model
    try:
        validated_fields = ContactFieldCreate(**contact_field_fields)
        # Convert to dict for API request
        contact_field_data = validated_fields.model_dump(exclude_none=True)
    except Exception as e:
        return _err("validation_error", f"Validation error: {str(e)}")
    try:
        resp = await _request("POST", "/contact_fields", json=contact_field_data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to create contact field", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.contacts.update")
async def update_contact_field(contact_field_id: int, contact_field_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update a contact field in Freshdesk."""
    try:
        resp = await _request("PUT", f"/contact_fields/{contact_field_id}", json=contact_field_fields)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update contact field", details={"status": e.response.status_code, "contact_field_id": contact_field_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")
@mcp.tool("fields.tickets.get_property")
async def get_field_properties(field_name: str):
    """Get properties of a specific field by name."""
    actual_field_name=field_name
    if field_name == "type":
        actual_field_name="ticket_type"
    try:
        resp = await _request("GET", "/ticket_fields")
        fields = resp.json()
    except Exception:
        return None
    # Filter the field by name
    matched_field = next((field for field in fields if field["name"] == actual_field_name), None)

    return matched_field

@mcp.prompt()
def prompt_create_ticket(
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

If you need to retrieve information about any fields (such as allowed values or internal keys), please use the `fields.tickets.get_property` tool.

Notes:
- The "type" field is **not** a custom field; it is a standard system field.
- The "type" field is required but should be passed as a top-level parameter, not within custom_fields.
Make sure to reference the correct keys from `fields.tickets.get_property` when constructing the payload.
"""

@mcp.prompt()
def prompt_create_reply(
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

@mcp.tool("companies.list")
async def list_companies(
    page: Annotated[int, Field(ge=1, description="Page number")] = 1,
    per_page: Annotated[int, Field(ge=1, le=100, description="Items per page")] = 30
) -> Dict[str, Any]:
    """List all companies in Freshdesk with pagination support."""
    params = {"page": page, "per_page": per_page}
    try:
        response = await _request("GET", "/companies", params=params)
        link_header = response.headers.get('Link', '')
        pagination_info = parse_link_header(link_header)
        companies = response.json()
        next_page = pagination_info.get("next")
        return _ok({"companies": companies}, pagination={
            "current_page": page,
            "next_page": next_page,
            "prev_page": pagination_info.get("prev"),
            "per_page": per_page
        }, next_call=(
            {"tool": "companies.list", "arguments": {"page": next_page, "per_page": per_page}}
            if next_page is not None else None
        ))
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch companies", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("companies.get")
async def view_company(company_id: int) -> Dict[str, Any]:
    """Get a company in Freshdesk."""
    try:
        resp = await _request("GET", f"/companies/{company_id}")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch company", details={"status": e.response.status_code, "company_id": company_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"company_id": company_id})

@mcp.tool("companies.search")
async def search_companies(query: str) -> Dict[str, Any]:
    """Search for companies in Freshdesk."""
    params = {"name": query}
    try:
        resp = await _request("GET", "/companies/autocomplete", params=params)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to search companies", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("companies.find_by_name")
async def find_company_by_name(name: str) -> Dict[str, Any]:
    """Find a company by name in Freshdesk."""
    params = {"name": name}
    try:
        resp = await _request("GET", "/companies/autocomplete", params=params)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to find company", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("fields.companies.list")
async def list_company_fields() -> Dict[str, Any]:
    """List all company fields in Freshdesk."""
    try:
        resp = await _request("GET", "/company_fields")
        return _ok({"company_fields": resp.json()})
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch company fields", details={"status": e.response.status_code})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}")

@mcp.tool("tickets.summary.get")
async def view_ticket_summary(ticket_id: int) -> Dict[str, Any]:
    """Get the summary of a ticket in Freshdesk."""
    try:
        resp = await _request("GET", f"/tickets/{ticket_id}/summary")
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to fetch ticket summary", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.summary.update")
async def update_ticket_summary(ticket_id: int, body: str) -> Dict[str, Any]:
    """Update the summary of a ticket in Freshdesk."""
    data = {
        "body": body
    }
    try:
        resp = await _request("PUT", f"/tickets/{ticket_id}/summary", json=data)
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to update ticket summary", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

@mcp.tool("tickets.summary.delete")
async def delete_ticket_summary(ticket_id: int) -> Dict[str, Any]:
    """Delete the summary of a ticket in Freshdesk."""
    try:
        resp = await _request("DELETE", f"/tickets/{ticket_id}/summary")
        if resp.status_code == 204:
            return _ok({"message": "Ticket summary deleted successfully"})
        # Some deployments may return 200 with a body
        return _ok(resp.json())
    except httpx.HTTPStatusError as e:
        return _err("http_error", "Failed to delete ticket summary", details={"status": e.response.status_code, "ticket_id": ticket_id})
    except Exception as e:
        return _err("unexpected_error", f"An unexpected error occurred: {str(e)}", details={"ticket_id": ticket_id})

def main():
    logging.info("Starting Freshdesk MCP server")
    try:
        _validate_env_or_raise()
    except Exception as e:
        logging.error(f"Configuration error: {e}")
        raise
    logging.info("Freshdesk MCP server ready")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
