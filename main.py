"""
Desktop Support Agent — Continuous Daemon
==========================================
Runs forever, polling the inbox every POLL_INTERVAL seconds.
Each new email is analysed by Ollama (Gemma4:31b-cloud):
  • Product complaint  → forwarded to vikas@ksaptech.com immediately
  • Everything else    → collected into an Excel decision chart and emailed

Usage:
  python main.py                      # continuous mode (default, polls every 5 min)
  python main.py --interval 120       # poll every 2 minutes
  python main.py --once               # single run then exit
  python main.py --dry-run            # analyse but send no emails
  python main.py --reconfigure        # re-run credential setup wizard
"""

import sys
import time
import json
import signal
import argparse
from datetime import datetime
from pathlib import Path

from config_manager import get_config, reconfigure
from email_handler import IMAPClient, SMTPClient, generate_complaint_token
from ai_analyzer import OllamaAnalyzer
from excel_reporter import build_excel

# Maps email category → (department display name, forwarding address)
DEPARTMENT_ROUTING = {
    "hr":         ("HR",         "hr@kasptech.com"),
    "marketing":  ("Marketing",  "marketing@kasptech.com"),
    "accounting": ("Accounting", "accounting@kasptech.com"),
}

OUTPUT_DIR   = Path(__file__).parent / "reports"
UID_STORE    = Path(__file__).parent / "processed_uids.json"
DEFAULT_POLL = 3600  # 1 hour

_stop_requested = False


# ── Signal / shutdown ─────────────────────────────────────────────────────────

def _handle_signal(sig, frame):
    global _stop_requested
    print("\n[Agent] Shutdown signal received — finishing current cycle …")
    _stop_requested = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── UID persistence ───────────────────────────────────────────────────────────

def load_processed_uids() -> set[str]:
    if UID_STORE.exists():
        with open(UID_STORE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_uids(uids: set[str]) -> None:
    with open(UID_STORE, "w") as f:
        json.dump(sorted(uids), f)


# ── Core processing cycle ─────────────────────────────────────────────────────

def process_cycle(config: dict, dry_run: bool, processed_uids: set[str]) -> int:
    """
    Fetch new emails, analyse, route, build Excel.
    Returns the number of emails processed this cycle.
    """
    # 1. Fetch new emails via IMAP
    imap = IMAPClient(config)
    imap.connect()
    new_emails = imap.fetch_new_emails(processed_uids)
    imap.disconnect()

    if not new_emails:
        return 0

    print(f"[Agent] Processing {len(new_emails)} new email(s) …\n")

    # 2. Analyse with Ollama
    analyzer = OllamaAnalyzer(config)
    analysed: list[dict] = []
    for em in new_emails:
        result = analyzer.analyse(em)
        em.update(result)
        em.pop("raw_bytes", None)
        em["action_taken"] = "Pending"
        analysed.append(em)

    # 3. Connect SMTP
    smtp = None
    if not dry_run:
        smtp = SMTPClient(config)
        smtp.connect()

    # 4. Route emails by category and auto-reply to customer
    for em in analysed:
        category = em.get("category", "")

        if em.get("is_product_complaint"):
            em["complaint_token"] = generate_complaint_token()
            if dry_run:
                print(f"[DRY-RUN] Would forward complaint: {em['subject']}")
                print(f"[DRY-RUN] Would reply to customer: {em['sender']}  (token: {em['complaint_token']})")
                em["action_taken"] = f"Forwarded + customer replied (dry-run) [{em['complaint_token']}]"
            else:
                smtp.forward_complaint(em)
                smtp.reply_to_customer(em)
                em["action_taken"] = f"Forwarded + customer replied [{em['complaint_token']}]"

        elif category in DEPARTMENT_ROUTING:
            dept_name, dept_email = DEPARTMENT_ROUTING[category]
            if dry_run:
                print(f"[DRY-RUN] Would forward to {dept_name} ({dept_email}): {em['subject']}")
                print(f"[DRY-RUN] Would reply to customer: {em['sender']}")
                em["action_taken"] = f"Forwarded to {dept_name} + customer replied (dry-run)"
            else:
                smtp.forward_to_department(em, dept_email, dept_name)
                smtp.reply_to_customer_department(em, dept_name)
                em["action_taken"] = f"Forwarded to {dept_name} + customer replied"

        else:
            em["action_taken"] = "Included in report"

    # 5. Build Excel report for this batch
    OUTPUT_DIR.mkdir(exist_ok=True)
    excel_path = build_excel(analysed, OUTPUT_DIR)

    # 6. Email the Excel report
    if dry_run:
        print(f"[DRY-RUN] Would email Excel report to {config['report_to']}")
    else:
        smtp.send_excel_report(excel_path)

    if smtp:
        smtp.disconnect()

    # 7. Mark all as processed
    for em in analysed:
        processed_uids.add(em["uid"])
    save_processed_uids(processed_uids)

    # 8. Print cycle summary
    _print_cycle_summary(analysed)
    return len(analysed)


def _print_cycle_summary(analysed: list[dict]) -> None:
    print("\n" + "─" * 64)
    print(f"  Cycle complete — {len(analysed)} email(s) processed")
    print("─" * 64)
    for em in analysed:
        imp    = em.get("importance", "").upper().ljust(8)
        subj   = em.get("subject", "")[:48].ljust(50)
        action = em.get("action_taken", "")
        print(f"  [{imp}] {subj} → {action}")
    print("─" * 64 + "\n")


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Desktop Support Email Agent")
    p.add_argument("--reconfigure", action="store_true",
                   help="Re-run the credential setup wizard.")
    p.add_argument("--dry-run",     action="store_true",
                   help="Analyse emails but do not send any messages.")
    p.add_argument("--once",        action="store_true",
                   help="Run a single cycle then exit.")
    p.add_argument("--interval",    type=int, default=DEFAULT_POLL,
                   help=f"Seconds between polls (default: {DEFAULT_POLL}).")
    return p.parse_args()


# ── Banner ────────────────────────────────────────────────────────────────────

def print_banner(config: dict, args: argparse.Namespace) -> None:
    print("\n" + "=" * 64)
    print("  Desktop Support Agent  |  Ollama Gemma4:31b-cloud")
    print("=" * 64)
    print(f"  Account      : {config['email']}")
    print(f"  Mode         : {config.get('fetch_mode', 'unread')}")
    print(f"  AI Model     : {config.get('ollama_model', 'gemma4:31b-cloud')}")
    print(f"  Complaints → : {config.get('complaint_to', 'vikas@ksaptech.com')}")
    print(f"  Reports    → : {config.get('report_to', 'sumant.chakravarty@gmail.com')}")
    if args.dry_run:
        print("  DRY-RUN  : no emails will be sent")
    if args.once:
        print("  RUN MODE : single cycle")
    else:
        print(f"  RUN MODE : continuous (every {args.interval}s)  —  Ctrl+C to stop")
    print("=" * 64 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    config = reconfigure() if args.reconfigure else get_config()
    print_banner(config, args)

    processed_uids = load_processed_uids()
    print(f"[Agent] Loaded {len(processed_uids)} previously-processed UID(s).\n")

    cycle = 0
    while not _stop_requested:
        cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[Agent] ── Cycle #{cycle} at {now} ──")

        try:
            count = process_cycle(config, args.dry_run, processed_uids)
            if count == 0:
                print(f"[Agent] No new emails found.\n")
        except Exception as exc:
            print(f"[Agent] ERROR in cycle: {exc}")
            import traceback
            traceback.print_exc()
            print("[Agent] Will retry on next poll.\n")

        if args.once or _stop_requested:
            break

        # Sleep in 1-second ticks so Ctrl+C is responsive
        next_at = datetime.fromtimestamp(
            time.time() + args.interval
        ).strftime("%H:%M:%S")
        print(f"[Agent] Next check at {next_at} (in {args.interval}s) …\n")
        for _ in range(args.interval):
            if _stop_requested:
                break
            time.sleep(1)

    print("[Agent] Stopped cleanly.")


if __name__ == "__main__":
    main()
