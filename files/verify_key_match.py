#!/usr/bin/env python3
"""
Verify API Key Match
Extract public key from private key to check if API key ID matches.
"""

import os
from cryptography.hazmat.primitives import serialization
import base64

def verify_key_match():
    print("=" * 60)
    print("🔍 VERIFYING API KEY MATCH")
    print("=" * 60)
    
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    print(f"API Key ID: {api_key_id}")
    
    # Load private key
    try:
        with open("kalshi-key.pem", "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        # Extract public key
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Calculate SHA256 hash of public key (this is often used to generate key IDs)
        from cryptography.hazmat.primitives import hashes
        digest = hashes.Hash(hashes.SHA256())
        digest.update(public_bytes)
        public_key_hash = digest.finalize()
        
        # Convert to hex and base64
        hex_hash = public_key_hash.hex()
        b64_hash = base64.b64encode(public_key_hash).decode()
        
        print(f"\n🔑 Public Key Analysis:")
        print(f"  Public key bytes: {len(public_bytes)}")
        print(f"  SHA256 hash (hex): {hex_hash[:32]}...")
        print(f"  SHA256 hash (b64): {b64_hash[:32]}...")
        
        # Check if API key ID matches any part of the hash
        api_key_short = api_key_id.replace('-', '')[:16].lower()
        hash_short = hex_hash[:16].lower()
        
        print(f"\n🔍 Comparison:")
        print(f"  API Key (no dashes, first 16): {api_key_short}")
        print(f"  Hash (first 16): {hash_short}")
        print(f"  Match: {'✅' if api_key_short == hash_short else '❌'}")
        
        # Try different formats
        api_key_formats = [
            api_key_id,
            api_key_id.replace('-', ''),
            api_key_id.upper(),
            api_key_id.lower()
        ]
        
        print(f"\n🎯 Possible API Key Formats:")
        for fmt in api_key_formats:
            if fmt in hex_hash or fmt in b64_hash:
                print(f"  ✅ Found match: {fmt}")
            else:
                print(f"  ❌ No match: {fmt}")
        
        print(f"\n💡 CONCLUSION:")
        print(f"If no matches found above, the API Key ID does not match this private key.")
        print(f"You need to:")
        print(f"1. Generate a new API key pair on Kalshi")
        print(f"2. Download the new private key")
        print(f"3. Use the new API Key ID")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    verify_key_match()
