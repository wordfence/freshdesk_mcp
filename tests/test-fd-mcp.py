import asyncio
from freshdesk_mcp.server import get_ticket, update_ticket

async def test_get_ticket():
    ticket_id = "1289" #Replace with a test ticket Id
    result = await get_ticket(ticket_id)
    print(result)


async def test_update_ticket():
    ticket_id = 1289 #Replace with a test ticket Id 
    ticket_fields = {"status": 5}
    result = await update_ticket(ticket_id, ticket_fields)
    print(result)

if __name__ == "__main__":
    asyncio.run(test_get_ticket())
    asyncio.run(test_update_ticket())