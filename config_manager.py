"""
Credential and configuration management.
On first run, prompts the user for email/IMAP/SMTP details and saves them to agent_config.json.
"""
import json
import getpass
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "agent_config.json"

KNOWN_PROVIDERS = {
    "1": {
        "name": "Gmail / Google Workspace",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
    },
    "2": {
        "name": "Outlook / Microsoft 365",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
    },
    "3": {
        "name": "Zoho Mail",
        "imap_host": "imap.zoho.com",
        "imap_port": 993,
        "smtp_host": "smtp.zoho.com",
        "smtp_port": 587,
    },
    "4": {"name": "Custom IMAP/SMTP"},
}


def load_config() -> dict | None:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return None


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n[OK] Configuration saved to: {CONFIG_FILE}")
    print("[!]  This file contains your password in plain text.")
    print("     Keep it secure and do not commit it to version control.\n")


def _prompt(label: str, default: str = "") -> str:
    if default:
        value = input(f"  {label} [{default}]: ").strip()
        return value or default
    return input(f"  {label}: ").strip()


def setup_credentials() -> dict:
    print("\n" + "=" * 60)
    print("  Desktop Support Agent — First-Time Setup")
    print("=" * 60)
    print("\nThis wizard will configure email access for your agent.")
    print("You will need IMAP/SMTP credentials (use an App Password")
    print("if you have 2-factor authentication enabled).\n")

    email = _prompt("Your email address", "sumant@ksaptech.com")

    print("\nSelect your email provider:")
    for k, v in KNOWN_PROVIDERS.items():
        print(f"  {k}. {v['name']}")
    choice = _prompt("Choice (1-4)", "1")
    provider = KNOWN_PROVIDERS.get(choice, KNOWN_PROVIDERS["4"])

    if provider["name"] == "Custom IMAP/SMTP":
        imap_host = _prompt("IMAP Host")
        imap_port = int(_prompt("IMAP Port (SSL)", "993"))
        smtp_host = _prompt("SMTP Host")
        smtp_port = int(_prompt("SMTP Port (TLS)", "587"))
    else:
        print(f"\n  Using: {provider['name']}")
        imap_host = provider["imap_host"]
        imap_port = provider["imap_port"]
        smtp_host = provider["smtp_host"]
        smtp_port = provider["smtp_port"]

    password = getpass.getpass("\n  Password (or App Password, input hidden): ")

    print("\n--- Ollama / AI Model ---")
    ollama_url = _prompt("Ollama base URL", "http://localhost:11434")
    ollama_model = _prompt("Ollama model name", "gemma4:31b-cloud")

    print("\n--- Notification Targets ---")
    complaint_to = _prompt("Forward COMPLAINTS to", "vikas@ksaptech.com")
    report_to    = _prompt("Send decision-chart REPORT to", "sumant.chakravarty@gmail.com")

    print("\n--- Email Fetch Settings ---")
    fetch_mode = _prompt("Fetch (unread / all / last7days)", "unread")

    config = {
        "email": email,
        "password": password,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "complaint_to": complaint_to,
        "report_to": report_to,
        "ollama_url": ollama_url.rstrip("/"),
        "ollama_model": ollama_model,
        "fetch_mode": fetch_mode,
    }

    save_config(config)
    return config


def get_config() -> dict:
    config = load_config()
    if config is None:
        config = setup_credentials()
    return config


def reconfigure() -> dict:
    """Force re-run of the setup wizard (e.g. --reconfigure flag)."""
    return setup_credentials()
