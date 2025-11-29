"""Test script for the new generate_gemini_response REST API function."""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from backend.app.services.gemini_service import generate_gemini_response


def test_gemini_rest_api():
    """Test the Gemini REST API function."""
    
    print("=" * 80)
    print("Testing Gemini REST API Function")
    print("=" * 80)
    
    # Test prompts
    test_prompts = [
        "Explain what a SQL injection attack is in one sentence.",
        "What are the top 3 security vulnerabilities in web applications?",
        "Describe a cross-site scripting (XSS) attack briefly."
    ]
    
    for i, prompt in enumerate(test_prompts, 1):
        print(f"\n{'='*80}")
        print(f"Test {i}/{len(test_prompts)}")
        print(f"{'='*80}")
        print(f"Prompt: {prompt}")
        print("-" * 80)
        
        try:
            result = generate_gemini_response(prompt)
            
            if "error" in result:
                print(f"❌ Error: {result['error']}")
                if "details" in result:
                    print(f"Details: {result['details'][:200]}...")
            else:
                print(f"✅ Success!")
                print(f"Model: {result.get('model', 'N/A')}")
                print(f"Response length: {len(result['text'])} characters")
                print("\nResponse:")
                print("-" * 80)
                print(result['text'])
                print("-" * 80)
                
        except Exception as e:
            print(f"❌ Exception: {type(e).__name__}: {e}")
    
    print(f"\n{'='*80}")
    print("Testing complete!")
    print("=" * 80)


if __name__ == "__main__":
    test_gemini_rest_api()
