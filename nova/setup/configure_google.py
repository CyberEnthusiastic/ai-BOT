"""Google OAuth2 setup wizard for Nova — configures Gmail + Calendar access.

Run with:
    python -m nova.setup.configure_google

What this does:
  1. Prompts you to place your google_credentials.json (from Google Cloud Console)
     into data/credentials/.
  2. Initiates the OAuth2 consent flow (opens browser).
  3. Saves the resulting token.json to data/credentials/.
  4. Verifies access by fetching your Gmail profile and calendar list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running as: python -m nova.setup.configure_google
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from nova.config import DATA_DIR  # noqa: E402 — after sys.path fix

CREDENTIALS_DIR = DATA_DIR / "credentials"
TOKEN_PATH = CREDENTIALS_DIR / "token.json"
GOOGLE_CREDS_PATH = CREDENTIALS_DIR / "google_credentials.json"

_ALL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

_BANNER = """
╔══════════════════════════════════════════════════════════════╗
║         Nova v2 — Google OAuth2 Setup Wizard                ║
╚══════════════════════════════════════════════════════════════╝
"""

_INSTRUCTIONS = """
This wizard will connect Nova to your Google account (Gmail + Calendar).

BEFORE YOU START
────────────────
1. Go to https://console.cloud.google.com/
2. Create a project (or select an existing one).
3. Enable these APIs:
     • Gmail API
     • Google Calendar API
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client IDs"
   • Application type: Desktop app
   • Click "Create", then "Download JSON"
5. Rename the downloaded file to:
     google_credentials.json
6. Place it in:
     {creds_dir}

Press Enter once you have placed the file there...
"""


def _check_imports() -> bool:
    missing = []
    for pkg, install_name in [
        ("google.auth", "google-auth"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("googleapiclient", "google-api-python-client"),
    ]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(install_name)
    if missing:
        print(f"\n[ERROR] Missing packages: {', '.join(missing)}")
        print(f"Install them with:\n  pip install {' '.join(missing)}")
        return False
    return True


def _run_oauth_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore

    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[Step 1/3] Starting OAuth2 flow...")
    print("  Your browser will open for Google sign-in.")
    print("  After authorising, return here.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_PATH), _ALL_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    TOKEN_PATH.write_text(creds.to_json())
    print(f"[Step 1/3] ✓ Token saved to: {TOKEN_PATH}")
    return creds


def _verify_gmail(creds) -> bool:
    try:
        from googleapiclient.discovery import build  # type: ignore

        print("\n[Step 2/3] Verifying Gmail access...")
        svc = build("gmail", "v1", credentials=creds)
        profile = svc.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "?")
        total = profile.get("messagesTotal", 0)
        print(f"[Step 2/3] ✓ Gmail connected: {email}  ({total} messages)")
        return True
    except Exception as exc:
        print(f"[Step 2/3] ✗ Gmail verification failed: {exc}")
        return False


def _verify_calendar(creds) -> bool:
    try:
        from googleapiclient.discovery import build  # type: ignore

        print("\n[Step 3/3] Verifying Calendar access...")
        svc = build("calendar", "v3", credentials=creds)
        result = svc.calendarList().list().execute()
        calendars = result.get("items", [])
        names = [c.get("summary", "?") for c in calendars[:5]]
        print(f"[Step 3/3] ✓ Calendar connected. Calendars found: {', '.join(names)}")
        return True
    except Exception as exc:
        print(f"[Step 3/3] ✗ Calendar verification failed: {exc}")
        return False


def _revoke_token() -> None:
    """Remove the saved token to force re-authentication."""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print(f"Token removed: {TOKEN_PATH}")
    else:
        print("No token found to revoke.")


def main() -> int:
    print(_BANNER)

    # ── Dependency check ──────────────────────────────────────────────────────
    if not _check_imports():
        return 1

    # ── Sub-command handling ──────────────────────────────────────────────────
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "revoke":
            _revoke_token()
            return 0
        elif cmd == "status":
            if TOKEN_PATH.exists():
                size = TOKEN_PATH.stat().st_size
                print(f"Token file exists: {TOKEN_PATH} ({size} bytes)")
            else:
                print(f"No token found at: {TOKEN_PATH}")
            if GOOGLE_CREDS_PATH.exists():
                print(f"Credentials file exists: {GOOGLE_CREDS_PATH}")
            else:
                print(f"No credentials file at: {GOOGLE_CREDS_PATH}")
            return 0
        else:
            print(f"Unknown command '{cmd}'. Valid: revoke, status")
            return 1

    # ── Interactive setup flow ────────────────────────────────────────────────
    print(_INSTRUCTIONS.format(creds_dir=CREDENTIALS_DIR))
    input()  # Wait for user to place the file

    if not GOOGLE_CREDS_PATH.exists():
        print(f"\n[ERROR] File not found: {GOOGLE_CREDS_PATH}")
        print("Please download google_credentials.json from Google Cloud Console")
        print("and place it in the credentials directory.")
        return 1

    # Validate it's valid JSON with required fields
    try:
        with open(GOOGLE_CREDS_PATH) as f:
            raw = json.load(f)
        client_info = raw.get("installed") or raw.get("web")
        if not client_info:
            print("[ERROR] Invalid credentials file — must be Desktop app OAuth2 credentials.")
            return 1
        client_id = client_info.get("client_id", "?")
        print(f"\nClient ID detected: {client_id[:30]}...")
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Could not parse credentials JSON: {exc}")
        return 1

    # Run the OAuth flow
    try:
        creds = _run_oauth_flow()
    except Exception as exc:
        print(f"\n[ERROR] OAuth flow failed: {exc}")
        return 1

    # Verify both services
    gmail_ok = _verify_gmail(creds)
    cal_ok = _verify_calendar(creds)

    print("\n" + "─" * 60)
    if gmail_ok and cal_ok:
        print("✓ Setup complete! Nova can now access your Gmail and Calendar.")
        print("  Token stored at:", TOKEN_PATH)
        print("\nTo revoke access later:")
        print("  python -m nova.setup.configure_google revoke")
    else:
        print("⚠ Setup finished with warnings. Check errors above.")
        print("  Nova may not have full access to Gmail or Calendar.")
    print("─" * 60)

    return 0 if (gmail_ok and cal_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
