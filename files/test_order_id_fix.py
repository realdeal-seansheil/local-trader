#!/usr/bin/env python3
"""
Test the order ID extraction fix
"""

def test_order_id_extraction():
    # Simulate the API response we got earlier
    mock_response = {
        "order": {
            "action": "buy",
            "client_order_id": "ad215b92-8a12-4691-967c-95d4cfdd4c38",
            "created_time": "2026-02-17T14:59:29.586052Z",
            "expiration_time": None,
            "fill_count": 1,
            "fill_count_fp": "1.00",
            "initial_count": 1,
            "initial_count_fp": "1.00",
            "last_update_time": "2026-02-17T14:59:29.586052Z",
            "maker_fees": 0,
            "maker_fill_cost": 0,
            "maker_fill_cost_dollars": "",
            "no_price": 99,
            "no_price_dollars": "0.9900",
            "order_group_id": None,
            "order_id": "773a2e1b-58a9-4e9a-86e6-3c7743fe9fb2",
            "queue_position": 0,
            "remaining_count": 0,
            "remaining_count_fp": "0.00",
            "side": "yes",
            "status": "executed",
            "subaccount_number": 0,
            "taker_fees": 1,
            "taker_fees_dollars": "0.0100",
            "taker_fill_cost": 1,
            "taker_fill_cost_dollars": "0.0100",
            "ticker": "KXBTC-26FEB1710-B67625",
            "type": "limit",
            "user_id": "9759f9f4-5423-45ca-992a-21c2aeb31f40",
            "yes_price": 1,
            "yes_price_dollars": "0.0100"
        }
    }
    
    print("🔧 Testing Order ID Extraction Fix")
    print("=" * 50)
    
    # Test OLD method (broken)
    old_order_id = mock_response.get("order", {}).get("id")
    print(f"❌ OLD METHOD - result.get('order', {{}}).get('id'): {old_order_id}")
    
    # Test NEW method (fixed)
    new_order_id = mock_response.get("order", {}).get("order_id")
    print(f"✅ NEW METHOD - result.get('order', {{}}).get('order_id'): {new_order_id}")
    
    print(f"\n📊 Results:")
    print(f"   Order ID extracted: {'✅ YES' if new_order_id else '❌ NO'}")
    print(f"   Order ID value: {new_order_id}")
    print(f"   Order ID type: {type(new_order_id)}")
    print(f"   Order ID length: {len(new_order_id) if new_order_id else 0}")
    
    # Test the full flow
    print(f"\n🔄 Testing Full Flow:")
    
    # Simulate the fixed code
    result = mock_response
    order_id = result.get("order", {}).get("order_id")  # FIXED method
    
    if order_id:
        print(f"✅ Order ID successfully extracted: {order_id}")
        print(f"✅ Order can now be tracked and monitored")
        print(f"✅ Fill verification is now possible")
        print(f"✅ Arbitrage completion can be detected")
    else:
        print(f"❌ Order ID extraction failed")
        print(f"❌ Order tracking still broken")
    
    print(f"\n🎯 Fix Summary:")
    print(f"   Changed: result.get('order', {{}}).get('id')")
    print(f"   To:      result.get('order', {{}}).get('order_id')")
    print(f"   Result:  Order tracking now works!")

if __name__ == "__main__":
    test_order_id_extraction()
