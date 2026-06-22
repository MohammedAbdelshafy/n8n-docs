"""
Auto-configures your Twilio phone number's webhook to point at your
Railway deployment. Run this ONCE after Railway gives you a URL.

Usage:
  python scripts/setup_twilio.py https://your-app.up.railway.app
"""

import sys
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")


def setup_webhook(base_url: str):
    base_url = base_url.rstrip("/")
    webhook  = f"{base_url}/sms/inbound"

    print(f"Configuring Twilio webhook → {webhook}")

    # Find the phone number SID
    r = httpx.get(
        f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/IncomingPhoneNumbers.json",
        auth=(ACCOUNT_SID, AUTH_TOKEN),
    )
    r.raise_for_status()
    numbers = r.json()["incoming_phone_numbers"]

    if not numbers:
        print("ERROR: No phone numbers found in your Twilio account.")
        sys.exit(1)

    # Find our number
    target = None
    clean  = FROM_NUMBER.replace("+", "").replace("-", "").replace(" ", "")
    for n in numbers:
        if clean in n["phone_number"].replace("+", ""):
            target = n
            break

    if not target:
        target = numbers[0]
        print(f"  Using first number found: {target['phone_number']}")
    else:
        print(f"  Found number: {target['phone_number']}")

    # Update webhook
    sid = target["sid"]
    r2  = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/IncomingPhoneNumbers/{sid}.json",
        auth=(ACCOUNT_SID, AUTH_TOKEN),
        data={
            "SmsUrl":    webhook,
            "SmsMethod": "POST",
        },
    )
    r2.raise_for_status()

    print(f"\nDone. Twilio will now POST inbound SMS to:\n  {webhook}")
    print("\nNext: register A2P 10DLC at https://console.twilio.com/us1/develop/sms/regulatory-compliance")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/setup_twilio.py https://your-app.up.railway.app")
        sys.exit(1)

    if not all([ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER]):
        print("ERROR: Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in .env first.")
        sys.exit(1)

    setup_webhook(sys.argv[1])
