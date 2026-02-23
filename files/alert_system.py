#!/usr/bin/env python3
"""
Alert System for Trading Bot
Sends notifications when trades are placed.
"""

import os
import json
import subprocess
from datetime import datetime

def send_alert(title, message, urgent=False):
    """Send an alert notification."""
    
    # Create alert message
    alert_data = {
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "message": message,
        "urgent": urgent
    }
    
    # Save to alert log
    alert_file = "data/alerts.jsonl"
    os.makedirs(os.path.dirname(alert_file), exist_ok=True)
    with open(alert_file, "a") as f:
        f.write(json.dumps(alert_data) + "\n")
    
    # Print to terminal
    print("\n" + "="*60)
    print(f"🚨 ALERT: {title}")
    print("="*60)
    print(f"🕐 Time: {alert_data['timestamp']}")
    print(f"📄 Message: {message}")
    print("="*60)
    
    # Try to send system notification (macOS)
    try:
        if urgent:
            subprocess.run([
                "osascript", "-e", f'display notification "{title}" with subtitle "{message}"'
            ], check=False)
        else:
            subprocess.run([
                "osascript", "-e", f'display notification "{title}" with subtitle "{message}"'
            ], check=False)
    except:
        pass  # Fallback to terminal only
    
    # Try to send email (if configured)
    try:
        # You could add email notifications here
        pass
    except:
        pass

def check_first_trade():
    """Check if first trade has been placed and send alert."""
    alert_file = "data/alerts.jsonl"
    
    if not os.path.exists(alert_file):
        return False
    
    # Read recent alerts
    with open(alert_file, "r") as f:
        lines = f.readlines()
    
    # Look for first execution success
    for line in lines:
        try:
            alert = json.loads(line.strip())
            if alert.get("title") == "🚀 FIRST TRADE EXECUTED":
                return True
        except:
            continue
    
    return False

def monitor_first_trade():
    """Monitor for first trade and send alert."""
    print("🔍 Monitoring for first trade execution...")
    
    # Check if first trade already happened
    if check_first_trade():
        print("✅ First trade already executed")
        return
    
    # Monitor log file for new trades
    log_file = "data/48hour_trading.jsonl"
    
    if not os.path.exists(log_file):
        print("❌ Trading log file not found")
        return
    
    print("📡 Watching for first trade...")
    
    # Get current file size
    last_size = os.path.getsize(log_file)
    
    while True:
        try:
            current_size = os.path.getsize(log_file)
            
            if current_size > last_size:
                # New data written, check for trades
                with open(log_file, "r") as f:
                    lines = f.readlines()
                
                # Check last few lines for trade execution
                for line in lines[-5:]:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("type") == "execution_success":
                            ticker = entry.get("data", {}).get("ticker", "Unknown")
                            profit = entry.get("data", {}).get("execution_summary", {}).get("total_expected_profit", 0)
                            
                            send_alert(
                                "🚀 FIRST TRADE EXECUTED!",
                                f"Arbitrage on {ticker}\nExpected profit: ${profit:.2f}\nCheck logs for details.",
                                urgent=True
                            )
                            return
                    except:
                        continue
                
                last_size = current_size
            
            # Wait before checking again
            import time
            time.sleep(5)  # Check every 5 seconds
            
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
            return
        except Exception as e:
            print(f"❌ Error monitoring: {e}")
            time.sleep(5)

if __name__ == "__main__":
    monitor_first_trade()
