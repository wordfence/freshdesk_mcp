import asyncio
from freshdesk_mcp.server import get_ticket, update_ticket, get_ticket_conversation, update_ticket_conversation,get_agents, list_canned_responses, list_solution_articles, list_solution_categories,list_solution_folders,list_groups,create_group,create_contact_field

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

async def test_get_agents():
    page = 1
    per_page = 30
    result = await get_agents(page, per_page)
    print(result)

async def test_list_canned_responses():
    result = await list_canned_responses()
    print(result)

async def test_list_solution_articles():
    result = await list_solution_articles()
    print(result)

async def test_list_solution_folders():
    category_id = 60000237037
    result = await list_solution_folders(category_id)
    print(result)

async def test_list_solution_categories():
    result = await list_solution_categories()
    print(result)

async def test_list_solution_articles():
    folder_id = 60000347598
    result = await list_solution_articles(folder_id)
    print(result)

async def test_list_groups():
    result = await list_groups()
    print(result)
async def test_create_group():
    group_fields = {
       
    }
    result = await create_group(group_fields)
    print(result)
async def test_create_contact_field():
    contact_field_fields = {
        "label": "Robot Humor Processor",
        "label_for_customers": "Robot Humor Processor",
        "type": "custom_dropdown",
        "description": "Measures how well this contact understands AI jokes",
        "required_for_agents": False,
        "displayed_for_customers": True,
        "customers_can_edit": True,
        "choices": [{"value":"Still rebooting brain.exe","position":1},
            {"value":"Laughs in binary","position":2},
            {"value":"Dad jokes only","position":3},
            {"value":"Gets AI humor 404: Not Found","position":4},
            {"value":"Certified AI Comedian","position":5},
            {"value":"Makes ChatGPT snort-laugh","position":6},
            {"value":"Could teach HAL 9000 to smile","position":7}
            ],
        "position":1
    }
    result = await create_contact_field(contact_field_fields)
    print(result)
if __name__ == "__main__":
    # asyncio.run(test_get_ticket())
    # asyncio.run(test_update_ticket())
    # asyncio.run(test_get_ticket_conversation())
    # asyncio.run(test_update_ticket_conversation())
    # asyncio.run(test_get_agents())
    # asyncio.run(test_list_canned_responses())
    # asyncio.run(test_list_solution_articles())
    # asyncio.run(test_list_solution_folders())
    # asyncio.run(test_list_solution_categories())
    # asyncio.run(test_list_groups())
    asyncio.run(test_create_contact_field())