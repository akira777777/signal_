import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path("src").resolve()))

from signal_group_sender.client import SignalApiClient, SignalApiError
from signal_group_sender.config import Settings


def test_send():
    settings = Settings.from_env(Path(".env"))
    client = SignalApiClient(settings)
    
    print("Connecting to Signal API...")
    try:
        accounts = client.list_accounts()
        print(f"Linked accounts: {accounts}")
        if settings.number in accounts:
            print(f"Active account {settings.number} is linked.")
            print("Listing groups...")
            groups = client.list_groups()
            print(f"Total groups found: {len(groups)}")
            for g in groups:
                print(f"Group name: {g.get('name')}, id: {g.get('id')}")
        else:
            print(
                f"Active account {settings.number} is NOT linked. "
                "Please link it using the QR code in the web panel."
            )
    except SignalApiError as exc:
        print(f"Signal API Error: {exc}")

if __name__ == "__main__":
    test_send()
