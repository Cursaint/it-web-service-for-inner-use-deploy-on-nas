"""Poll the IT Service site and show Windows notifications for unread tickets."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


SITE_URL = os.environ.get("IT_SERVICE_URL", "http://localhost:8000").rstrip("/")
POLL_SECONDS = int(os.environ.get("IT_SERVICE_POLL_SECONDS", "15"))
SCRIPT_DIR = Path(__file__).resolve().parent
TOAST_SCRIPT = SCRIPT_DIR / "show_ticket_toast.ps1"
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ITServiceTicketNotifier"
APP_DATA.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DATA / "notified_tickets.json"
logging.basicConfig(
    filename=APP_DATA / "notifier.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def fetch_unread_tickets() -> list[dict]:
    request = Request(
        f"{SITE_URL}/api/notifications",
        headers={"Accept": "application/json", "User-Agent": "ITServiceTicketNotifier/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("tickets", [])


def show_notification(ticket: dict) -> None:
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-File", str(TOAST_SCRIPT),
            "-TicketNumber", str(ticket.get("request_number") or ticket.get("id")),
            "-Subject", str(ticket.get("subject") or "New IT ticket"),
            "-SiteUrl", SITE_URL,
        ],
        check=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> None:
    logging.info("Ticket notifier started for %s", SITE_URL)
    try:
        notified_ids = {int(ticket_id) for ticket_id in json.loads(STATE_FILE.read_text())}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        notified_ids: set[int] = set()
    while True:
        try:
            unread_tickets = fetch_unread_tickets()
            current_ids = set()
            for ticket in unread_tickets:
                ticket_id = int(ticket["id"])
                current_ids.add(ticket_id)
                if ticket_id not in notified_ids:
                    show_notification(ticket)
                    notified_ids.add(ticket_id)
                    STATE_FILE.write_text(json.dumps(sorted(notified_ids)))
                    logging.info("Displayed notification for ticket %s", ticket_id)
            # If a ticket is opened and later unread state changes, a later new
            # ticket ID can still notify normally without growing state forever.
            notified_ids.intersection_update(current_ids)
            STATE_FILE.write_text(json.dumps(sorted(notified_ids)))
        except (URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logging.warning("Unable to check ticket notifications: %s", exc)
        except Exception:
            logging.exception("Unexpected notifier error")
        time.sleep(max(POLL_SECONDS, 5))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
