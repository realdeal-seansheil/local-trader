#!/usr/bin/env python3
"""
Extract Key Information
Try different ways to extract key information from the private key.
"""

import os
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
import hashlib

def extract_key_info():
    print("=" * 60)
    print("🔍 EXTRACTING KEY INFORMATION")
    print("=" * 60)
    
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    print(f"Provided API Key ID: {api_key_id}")
    
    # Load private key
    try:
        with open("kalshi-key.pem", "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        print("✅ Private key loaded successfully")
    except Exception as e:
        print(f"❌ Private key error: {e}")
        return
    
    # Get public key
    public_key = private_key.public_key()
    
    # Try different hash methods
    hash_methods = [
        ("SHA256", hashes.SHA256()),
        ("SHA1", hashes.SHA1()),
        ("MD5", hashes.MD5()),
    ]
    
    print(f"\n🔍 Testing different hash methods:")
    
    for name, hash_alg in hash_methods:
        # Get public key bytes
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Calculate hash
        digest = hashes.Hash(hash_alg)
        digest.update(public_bytes)
        hash_result = digest.finalize()
        
        # Convert to different formats
        hex_hash = hash_result.hex()
        b64_hash = base64.b64encode(hash_result).decode()
        
        print(f"\n{name}:")
        print(f"  Hex (full): {hex_hash}")
        print(f"  Hex (first 16): {hex_hash[:16]}")
        print(f"  B64 (first 16): {b64_hash[:16]}")
        
        # Check if API key ID matches any part
        api_key_clean = api_key_id.replace('-', '').lower()
        hex_clean = hex_hash.lower()
        b64_clean = b64_hash.lower()
        
        if api_key_clean in hex_clean:
            print(f"  ✅ API key found in hex hash!")
            print(f"  Position: {hex_clean.find(api_key_clean)}")
        elif api_key_clean in b64_clean:
            print(f"  ✅ API key found in base64 hash!")
            print(f"  Position: {b64_clean.find(api_key_clean)}")
        else:
            print(f"  ❌ No match found")
    
    # Try extracting key parameters
    print(f"\n🔑 Private Key Parameters:")
    try:
        key_numbers = private_key.private_numbers()
        public_numbers = key_numbers.public_numbers
        
        print(f"  Key size: {private_numbers.key_size} bits")
        print(f"  Modulus (first 16 hex): {hex(public_numbers.n)[:16]}")
        print(f"  Exponent: {public_numbers.e}")
        
        # Try using modulus as key ID
        modulus_hex = hex(public_numbers.n)
        if api_key_clean in modulus_hex:
            print(f"  ✅ API key found in modulus!")
        else:
            print(f"  ❌ API key not in modulus")
            
    except Exception as e:
        print(f"  ❌ Error extracting parameters: {e}")
    
    # Try different encoding of API key
    print(f"\n🔍 API Key Formats:")
    formats = [
        ("Original", api_key_id),
        ("No dashes", api_key_id.replace('-', '')),
        ("Uppercase", api_key_id.upper()),
        ("Lowercase", api_key_id.lower()),
        ("First 8", api_key_id[:8]),
        ("Last 8", api_key_id[-8:]),
        ("First 16", api_key_id[:16]),
        ("Last 16", api_key_id[-16:]),
    ]
    
    for name, formatted in formats:
        print(f"  {name}: {formatted}")
    
    print(f"\n💡 CONCLUSION:")
    print(f"If no matches found above, Kalshi might:")
    print(f"1. Use a different method to generate API key IDs")
    print(f"2. Have specific formatting requirements")
    print(f"3. Use a different hashing algorithm")
    print(f"4. Have account-specific key generation")

if __name__ == "__main__":
    extract_key_info()
