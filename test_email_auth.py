#!/usr/bin/env python3
"""
Test script for email authentication system.
This script tests the complete user registration and verification flow.
"""

import asyncio
import requests
import json
from datetime import datetime

# API base URL
BASE_URL = "http://localhost:8000/api/v1/auth"

def test_register_user():
    """Test user registration."""
    print("\n=== Testing User Registration ===")
    
    # Generate unique username and email
    timestamp = int(datetime.now().timestamp())
    username = f"testuser{timestamp}"
    email = f"test{timestamp}@example.com"
    
    payload = {
        "username": username,
        "email": email,
        "password": "testpassword123"
    }
    
    response = requests.post(f"{BASE_URL}/register", json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        print("✅ Registration successful")
        return username, email
    else:
        print("❌ Registration failed")
        return None, None

def test_send_verification(email):
    """Test sending verification code."""
    print("\n=== Testing Verification Code Sending ===")
    
    payload = {
        "email": email
    }
    
    response = requests.post(f"{BASE_URL}/send-verification", json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        print("✅ Verification code sent successfully")
        return True
    else:
        print("❌ Failed to send verification code")
        return False

def test_login_before_verification(username):
    """Test login before email verification."""
    print("\n=== Testing Login Before Verification ===")
    
    payload = {
        "username": username,
        "password": "testpassword123"
    }
    
    # Using form data for OAuth2 password flow
    response = requests.post(
        f"{BASE_URL}/token",
        data={
            "username": username,
            "password": "testpassword123"
        }
    )
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 400:
        print("✅ Login correctly blocked before verification")
        return True
    else:
        print("❌ Login should be blocked before verification")
        return False

def test_verify_email(email, verification_code):
    """Test email verification."""
    print("\n=== Testing Email Verification ===")
    
    payload = {
        "email": email,
        "verification_code": verification_code
    }
    
    response = requests.post(f"{BASE_URL}/verify-email", json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        print("✅ Email verification successful")
        return True
    else:
        print("❌ Email verification failed")
        return False

def test_login_after_verification(username):
    """Test login after email verification."""
    print("\n=== Testing Login After Verification ===")
    
    response = requests.post(
        f"{BASE_URL}/token",
        data={
            "username": username,
            "password": "testpassword123"
        }
    )
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        token_data = response.json()
        print(f"✅ Login successful")
        print(f"Access Token: {token_data['access_token'][:50]}...")
        return True
    else:
        print(f"❌ Login failed: {response.json()}")
        return False

def test_invalid_verification_code(email):
    """Test with invalid verification code."""
    print("\n=== Testing Invalid Verification Code ===")
    
    payload = {
        "email": email,
        "verification_code": "000000"  # Invalid code
    }
    
    response = requests.post(f"{BASE_URL}/verify-email", json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 400:
        print("✅ Invalid verification code correctly rejected")
        return True
    else:
        print("❌ Invalid verification code should be rejected")
        return False

def test_duplicate_registration(username, email):
    """Test duplicate username/email registration."""
    print("\n=== Testing Duplicate Registration ===")
    
    payload = {
        "username": username,
        "email": email,
        "password": "anotherpassword"
    }
    
    response = requests.post(f"{BASE_URL}/register", json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 400:
        print("✅ Duplicate registration correctly rejected")
        return True
    else:
        print("❌ Duplicate registration should be rejected")
        return False

async def main():
    """Run all tests."""
    print("Starting Email Authentication System Tests")
    print("=" * 50)
    
    # Note: For actual testing, you would need to:
    # 1. Start the server
    # 2. Configure email settings in .env
    # 3. Check the actual verification code from email
    
    print("\n⚠️  Note: This is a demonstration of the API endpoints.")
    print("For full testing, you need to:")
    print("1. Start the server with 'python main.py'")
    print("2. Configure email settings in .env file")
    print("3. Check the actual verification code from email")
    
    # Test registration
    username, email = test_register_user()
    if not username:
        print("\n❌ Cannot proceed with tests - registration failed")
        return
    
    # Test duplicate registration
    test_duplicate_registration(username, email)
    
    # Test sending verification code
    test_send_verification(email)
    
    # Test login before verification
    test_login_before_verification(username)
    
    # Test invalid verification code
    test_invalid_verification_code(email)
    
    print("\n" + "=" * 50)
    print("Testing complete!")
    print("\nTo complete the verification test:")
    print(f"1. Check email at: {email}")
    print("2. Get the verification code")
    print("3. Run: test_verify_email(email, actual_code)")
    print("4. Run: test_login_after_verification(username)")

if __name__ == "__main__":
    asyncio.run(main())