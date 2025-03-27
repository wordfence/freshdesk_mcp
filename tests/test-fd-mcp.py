import asyncio
from freshdesk_mcp.server import get_ticket, update_ticket, get_ticket_conversation, update_ticket_conversation

async def test_get_ticket():
    ticket_id = "1289" #Replace with a test ticket Id
    result = await get_ticket(ticket_id)
    print(result)


async def test_update_ticket():
    ticket_id = 1289 #Replace with a test ticket Id 
    ticket_fields = {"status": 5}
    result = await update_ticket(ticket_id, ticket_fields)
    print(result)

async def test_get_ticket_conversation():
    ticket_id = 1294 #Replace with a test ticket Id 
    result = await get_ticket_conversation(ticket_id)
    print(result)

async def test_update_ticket_conversation():
    conversation_id = 60241927935 #Replace with a test conversation Id 
    body = "This is a test reply"
    result = await update_ticket_conversation(conversation_id, body)
    print(result)


if __name__ == "__main__":
    asyncio.run(test_get_ticket())
    asyncio.run(test_update_ticket())
    asyncio.run(test_get_ticket_conversation())
    asyncio.run(test_update_ticket_conversation())