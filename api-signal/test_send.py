import sys
import os
import asyncio
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path("src").resolve()))

from signal_group_sender.telegram_config import TelegramSettings
from signal_group_sender.telegram_client import TelegramApiClient, _telethon_runtime

def test_send():
    settings = TelegramSettings.from_env(Path(".env"))
    client = TelegramApiClient(settings)
    runtime = _telethon_runtime()
    
    print("Connecting to Telegram...")
    async def run_op(tg_client):
        print("Checking authorization...")
        authorized = await tg_client.is_user_authorized()
        print(f"Authorized: {authorized}")
        if authorized:
            me = await tg_client.get_me()
            try:
                first_name = (getattr(me, 'first_name', '') or '').encode('ascii', errors='replace').decode('ascii')
                last_name = (getattr(me, 'last_name', '') or '').encode('ascii', errors='replace').decode('ascii')
                username = (getattr(me, 'username', '') or '').encode('ascii', errors='replace').decode('ascii')
            except Exception:
                first_name = last_name = username = "unknown"
            print(f"Logged in as: {first_name} {last_name} (@{username}), ID: {getattr(me, 'id', '')}, Phone: +{getattr(me, 'phone', '')}")
        if not authorized:
            print("Not authorized! Please log in via the web panel first.")
            return
        
        print("Listing ALL dialogs safely...")
        found_target = None
        async for dialog in tg_client.iter_dialogs():
            entity = getattr(dialog, 'entity', None)
            if entity:
                peer_id = str(runtime.get_peer_id(entity))
                try:
                    title_bytes = dialog.title.encode('ascii', errors='replace').decode('ascii')
                except Exception:
                    title_bytes = "unknown"
                print(f"Dialog: '{title_bytes}', peer_id: {peer_id}, Type: {type(entity).__name__}")
                if peer_id == "-1002541562709" or peer_id == "2541562709" or "2541562709" in peer_id:
                    found_target = (dialog, entity)
        
        if found_target:
            dialog, entity = found_target
            print(f"Found target dialog!")
            print(f"Creator: {getattr(entity, 'creator', None)}")
            print(f"Left: {getattr(entity, 'left', None)}")
            print(f"Deactivated: {getattr(entity, 'deactivated', None)}")
            print(f"Admin rights: {getattr(entity, 'admin_rights', None)}")
            print(f"Banned rights: {getattr(entity, 'banned_rights', None)}")
            print(f"Default banned rights: {getattr(entity, 'default_banned_rights', None)}")
            print(f"Permissions: {getattr(entity, 'permissions', None)}")
            print(f"Restricted: {getattr(entity, 'restricted', None)}")
            
            # Let's run the checks
            is_group = isinstance(entity, runtime.chat_type)
            is_supergroup = isinstance(entity, runtime.channel_type) and getattr(entity, "megagroup", False)
            print(f"is_group: {is_group}, is_supergroup: {is_supergroup}")
            is_active = (
                client._is_active_group(entity)
                if is_group
                else client._is_active_supergroup(entity)
            )
            print(f"is_active: {is_active}")
            can_send = client._can_send_in_chat_now(entity)
            can_send_media = client._can_send_media_in_chat_now(entity)
            print(f"can_send: {can_send}, can_send_media: {can_send_media}")
        else:
            print("Target peer_id -1002541562709 NOT found in dialogs!")

    try:
        client._run(run_op)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_send()
