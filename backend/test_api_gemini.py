"""Test script for the new /api/gemini endpoint."""

import requests
import json

# Configuration
BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/gemini"


def test_gemini_endpoint():
    """Test the /api/gemini endpoint with various prompts."""
    
    print("=" * 80)
    print("Testing /api/gemini Endpoint")
    print("=" * 80)
    
    # Test cases
    test_cases = [
        {
            "name": "SQL Injection",
            "prompt": "Explain what a SQL injection attack is in one sentence."
        },
        {
            "name": "XSS Attack",
            "prompt": "What is a cross-site scripting (XSS) attack?"
        },
        {
            "name": "OWASP Top 10",
            "prompt": "List the OWASP Top 10 vulnerabilities briefly."
        },
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"Test {i}/{len(test_cases)}: {test_case['name']}")
        print(f"{'='*80}")
        print(f"Prompt: {test_case['prompt']}")
        print("-" * 80)
        
        try:
            # Make POST request
            response = requests.post(
                ENDPOINT,
                json={"prompt": test_case["prompt"]},
                headers={"Content-Type": "application/json"},
                timeout=35
            )
            
            # Parse response
            data = response.json()
            
            # Check if successful
            if response.status_code == 200 and data.get("success"):
                print(f"✅ Status: {response.status_code} OK")
                print(f"Model: {data.get('model', 'N/A')}")
                print(f"Metadata: {json.dumps(data.get('metadata', {}), indent=2)}")
                print("\nResponse:")
                print("-" * 80)
                print(data.get("response", "No response text"))
                print("-" * 80)
            else:
                print(f"❌ Status: {response.status_code}")
                print(f"Error: {data.get('error', 'Unknown error')}")
                if "details" in data:
                    print(f"Details: {data['details'][:200]}...")
                    
        except requests.exceptions.Timeout:
            print("❌ Request timed out after 35 seconds")
        except requests.exceptions.ConnectionError:
            print("❌ Connection error - is the backend running on port 8000?")
        except Exception as e:
            print(f"❌ Unexpected error: {type(e).__name__}: {e}")
    
    print(f"\n{'='*80}")
    print("Testing complete!")
    print("=" * 80)


def test_error_cases():
    """Test error handling."""
    
    print("\n" + "=" * 80)
    print("Testing Error Cases")
    print("=" * 80)
    
    # Test empty prompt
    print("\nTest: Empty prompt")
    print("-" * 80)
    try:
        response = requests.post(
            ENDPOINT,
            json={"prompt": ""},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        data = response.json()
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test missing prompt
    print("\nTest: Missing prompt field")
    print("-" * 80)
    try:
        response = requests.post(
            ENDPOINT,
            json={},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        data = response.json()
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("\n🚀 Starting /api/gemini endpoint tests...\n")
    
    # Check if server is running
    try:
        health_response = requests.get(f"{BASE_URL}/health", timeout=5)
        if health_response.status_code == 200:
            print(f"✅ Backend server is running at {BASE_URL}")
            print(f"✅ Health check: {health_response.json()}\n")
        else:
            print(f"⚠️  Backend server returned status {health_response.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to backend server at {BASE_URL}")
        print("Please start the backend with: python -m uvicorn backend.app.main:app --reload")
        exit(1)
    
    # Run tests
    test_gemini_endpoint()
    test_error_cases()
