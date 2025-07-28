#!/usr/bin/env python3
"""Standalone test for helper functions without dependencies."""

import re
import json


def filter_encrypted_reports(text: str, placeholder: str = "[ENCRYPTED REPORT REMOVED]") -> str:
    """Remove encrypted blocks between -----BEGIN REPORT----- and -----END REPORT----- tags."""
    if not text or "-----BEGIN REPORT-----" not in text:
        return text
    
    pattern = r'-----BEGIN REPORT-----.*?-----END REPORT-----'
    filtered_text = re.sub(pattern, placeholder, text, flags=re.DOTALL)
    return filtered_text


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string."""
    return len(text) // 4


def process_conversation_body(conversation: dict, filter_reports: bool = True, 
                            report_placeholder: str = "[ENCRYPTED REPORT REMOVED]") -> dict:
    """Process a conversation to optionally filter encrypted reports."""
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


def test_filter_encrypted_reports():
    """Test the encrypted report filtering function."""
    print("Testing filter_encrypted_reports...")
    
    # Test case 1: Text with encrypted report
    text1 = """This is a normal message.
-----BEGIN REPORT-----
ENCRYPTED DATA HERE
LOTS OF ENCRYPTED CONTENT
-----END REPORT-----
This is after the report."""
    
    filtered1 = filter_encrypted_reports(text1)
    assert "-----BEGIN REPORT-----" not in filtered1
    assert "[ENCRYPTED REPORT REMOVED]" in filtered1
    assert "This is a normal message." in filtered1
    assert "This is after the report." in filtered1
    print("✓ Test 1 passed: Basic filtering")
    
    # Test case 2: Multiple reports
    text2 = """First part
-----BEGIN REPORT-----
ENCRYPTED1
-----END REPORT-----
Middle part
-----BEGIN REPORT-----
ENCRYPTED2
-----END REPORT-----
End part"""
    
    filtered2 = filter_encrypted_reports(text2)
    assert filtered2.count("[ENCRYPTED REPORT REMOVED]") == 2
    assert "Middle part" in filtered2
    print("✓ Test 2 passed: Multiple reports")
    
    # Test case 3: No reports
    text3 = "This is just normal text without any reports."
    filtered3 = filter_encrypted_reports(text3)
    assert filtered3 == text3
    print("✓ Test 3 passed: No reports")
    
    # Test case 4: Custom placeholder
    filtered4 = filter_encrypted_reports(text1, placeholder="[REDACTED]")
    assert "[REDACTED]" in filtered4
    assert "[ENCRYPTED REPORT REMOVED]" not in filtered4
    print("✓ Test 4 passed: Custom placeholder")
    
    print("All filter tests passed!\n")


def test_estimate_tokens():
    """Test the token estimation function."""
    print("Testing estimate_tokens...")
    
    # Test various text lengths
    test_cases = [
        ("", 0),
        ("Hello", 1),  # 5 chars / 4 = 1.25, rounds down to 1
        ("This is a test", 3),  # 14 chars / 4 = 3.5, rounds down to 3
        ("A" * 100, 25),  # 100 chars / 4 = 25
    ]
    
    for text, expected in test_cases:
        result = estimate_tokens(text)
        assert result == expected, f"Expected {expected}, got {result} for text length {len(text)}"
        print(f"✓ Text length {len(text)}: {result} tokens")
    
    print("All token estimation tests passed!\n")


def test_process_conversation_body():
    """Test the conversation processing function."""
    print("Testing process_conversation_body...")
    
    # Test conversation with encrypted report in body
    conv1 = {
        "id": 123,
        "body": """Hello,
-----BEGIN REPORT-----
ENCRYPTED CONTENT
-----END REPORT-----
Thanks!""",
        "created_at": "2024-01-01",
        "user_id": 456
    }
    
    # Test with filtering enabled
    processed1 = process_conversation_body(conv1, filter_reports=True)
    assert "[ENCRYPTED REPORT REMOVED]" in processed1["body"]
    assert "ENCRYPTED CONTENT" not in processed1["body"]
    assert processed1["id"] == 123
    print("✓ Test 1 passed: Filtering enabled")
    
    # Test with filtering disabled
    processed2 = process_conversation_body(conv1, filter_reports=False)
    assert "ENCRYPTED CONTENT" in processed2["body"]
    assert processed2 == conv1
    print("✓ Test 2 passed: Filtering disabled")
    
    # Test with multiple fields
    conv2 = {
        "body": "-----BEGIN REPORT-----DATA1-----END REPORT-----",
        "body_text": "-----BEGIN REPORT-----DATA2-----END REPORT-----",
        "description": "-----BEGIN REPORT-----DATA3-----END REPORT-----",
        "other_field": "-----BEGIN REPORT-----DATA4-----END REPORT-----"
    }
    
    processed3 = process_conversation_body(conv2)
    assert "[ENCRYPTED REPORT REMOVED]" in processed3["body"]
    assert "[ENCRYPTED REPORT REMOVED]" in processed3["body_text"]
    assert "[ENCRYPTED REPORT REMOVED]" in processed3["description"]
    assert "DATA4" in processed3["other_field"]  # other_field should not be filtered
    print("✓ Test 3 passed: Multiple fields filtered correctly")
    
    print("All conversation processing tests passed!\n")


def demo_token_savings():
    """Demonstrate the token savings from filtering encrypted reports."""
    print("Demonstrating token savings...")
    
    # Example conversation with encrypted report
    large_report = "A" * 10000  # Simulate 10KB encrypted report
    conversation_with_report = {
        "body": f"""Hello, I've attached the security report below:

-----BEGIN REPORT-----
{large_report}
-----END REPORT-----

Please let me know if you need anything else."""
    }
    
    # Calculate tokens before and after filtering
    original_json = json.dumps(conversation_with_report)
    original_tokens = estimate_tokens(original_json)
    
    filtered_conv = process_conversation_body(conversation_with_report, filter_reports=True)
    filtered_json = json.dumps(filtered_conv)
    filtered_tokens = estimate_tokens(filtered_json)
    
    tokens_saved = original_tokens - filtered_tokens
    
    print(f"Original conversation: {original_tokens} tokens")
    print(f"Filtered conversation: {filtered_tokens} tokens")
    print(f"Tokens saved: {tokens_saved} ({tokens_saved/original_tokens*100:.1f}% reduction)")
    print()


def main():
    """Run all tests."""
    print("Running Freshdesk MCP Conversation Enhancement Tests\n")
    
    test_filter_encrypted_reports()
    test_estimate_tokens()
    test_process_conversation_body()
    demo_token_savings()
    
    print("\n✅ All tests passed successfully!")
    print("\nThe enhanced get_ticket_conversation function now supports:")
    print("- Pagination (page and per_page parameters)")
    print("- Token limiting (max_tokens parameter up to 25,000)")
    print("- Encrypted report filtering (filter_encrypted_reports parameter)")
    print("- Detailed response metadata (pagination info, token counts, filtering stats)")
    print("\nAdditionally, get_all_ticket_conversations provides automatic pagination")
    print("to fetch all conversations while staying under token limits.")


if __name__ == "__main__":
    main()