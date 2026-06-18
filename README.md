# Desktop Support Agent

An automated email monitoring agent that reads a Gmail inbox, classifies every new email using a local Ollama AI model (Gemma4:31b-cloud), and routes each one to the right recipient.

---

## What It Does

```
New email arrives in sumant@ksaptech.com
          │
          ▼
  AI analyses the email
  (category + importance + complaint check)
          │
    ┌─────┴──────┐
    │            │
 Complaint    Not a complaint
    │            │
    ▼            ▼
vikas@        sumant.chakravarty@gmail.com
ksaptech.com  (Excel decision chart attached)
 & recieving Reply to complainer also.

- **Product complaint** → forwarded immediately to `vikas@ksaptech.com` with the note *"Its important as it complain of product"*
- **All other emails** → batched into a colour-coded Excel decision chart and emailed to `sumant.chakravarty@gmail.com`
- Runs as a **continuous daemon**, polling every 5 minutes (configurable)
- Tracks processed emails in `processed_uids.json` — no email is ever analysed twice, even across restarts

---

## Requirements

| Requirement | Details |
|---|---|
| Python | 3.10 or higher |
| Ollama | Running locally at `http://localhost:11434` |
| Ollama model | `gemma4:31b-cloud` pulled and available |
| Gmail account | IMAP enabled + App Password generated |

### Python packages

```
requests>=2.31.0
openpyxl>=3.1.2
```

Install with:

```bash
pip install -r requirements.txt
```

---

## First-Time Setup

### 1. Enable Gmail IMAP

1. Open Gmail → **Settings** → **See all settings**
2. Go to the **Forwarding and POP/IMAP** tab
3. Under **IMAP access**, select **Enable IMAP**
4. Save changes

### 2. Generate a Gmail App Password

> Required if you have 2-Factor Authentication enabled (recommended).

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Select app: **Mail**, device: **Windows Computer**
3. Copy the 16-character password (e.g. `kaaa aabc jyaw srkb`)

### 3. Start Ollama and pull the model

```bash
ollama serve
ollama pull gemma4:31b-cloud
```

### 4. Run the agent (first time)

```bash
python main.py
```

The setup wizard will ask for your credentials and save them to `agent_config.json`.

---

## Usage

```bash
# Continuous mode (default) — polls every 5 minutes
python main.py

# Custom poll interval (e.g. every 2 minutes)
python main.py --interval 120

# Single run then exit
python main.py --once

# Analyse without sending any emails (safe for testing)
python main.py --dry-run

# Re-run the credential setup wizard
python main.py --reconfigure
```

Press **Ctrl+C** to stop the daemon cleanly.

---

## Configuration (`agent_config.json`)

Created automatically on first run. You can edit it directly.

| Key | Description | Example |
|---|---|---|
| `email` | Inbox to monitor | `sumant@ksaptech.com` |
| `password` | Gmail App Password | `**** **** **** ****N` |
| `imap_host` | IMAP server | `imap.gmail.com` |
| `imap_port` | IMAP port (SSL) | `993` |
| `smtp_host` | SMTP server | `smtp.gmail.com` |
| `smtp_port` | SMTP port (TLS) | `587` |
| `complaint_to` | Complaint forward address | `vikas@ksaptech.com` |
| `report_to` | Excel report address | `sumant.chakravarty@gmail.com` |
| `ollama_url` | Ollama base URL | `http://localhost:11434` |
| `ollama_model` | Model to use | `gemma4:31b-cloud` |
| `fetch_mode` | Initial fetch scope | `unread` / `last7days` / `all` |

> **Security note:** `agent_config.json` contains your App Password in plain text. Do not commit it to version control. Add it to `.gitignore`.

---

## Email Categories

The AI classifies every email into one of these categories:

| Category | Description |
|---|---|
| `product_complaint` | Complaint about a product defect or dissatisfaction |
| `billing_issue` | Invoice, payment, or subscription problems |
| `technical_support` | Technical help requests |
| `feature_request` | Requests for new features |
| `general_inquiry` | General questions |
| `newsletter_or_promo` | Marketing emails and newsletters |
| `spam` | Unsolicited mail |
| `internal_communication` | Internal company emails |
| `order_status` | Order tracking and delivery |
| `feedback` | General feedback (not a complaint) |
| `other` | Anything that doesn't fit above |

### Importance Levels

| Level | Colour in Excel |
|---|---|
| Critical | Red |
| High | Orange |
| Medium | Yellow |
| Low | Green |

---

## Output Files

| File | Description |
|---|---|
| `agent_config.json` | Credentials and settings |
| `processed_uids.json` | UIDs of all processed emails (prevents duplicates) |
| `reports/email_decision_chart_YYYYMMDD_HHMMSS.xlsx` | Excel report per cycle |

### Excel Report Tabs

1. **Summary** — total counts, complaint count, importance breakdown
2. **Decision Chart** — one row per email with category, importance, AI summary, action taken
3. **Category Breakdown** — count and percentage per category

---

## Project Structure

```
desktopSupport_Agent/
├── main.py               Daemon loop, CLI entry point
├── config_manager.py     First-run wizard, credential storage
├── email_handler.py      IMAP reader, SMTP sender/forwarder
├── ai_analyzer.py        Ollama integration, keyword fallback
├── excel_reporter.py     Excel decision chart builder
├── requirements.txt      Python dependencies
├── agent_config.json     Generated on first run (keep private)
├── processed_uids.json   Generated at runtime (tracks seen emails)
└── reports/              Excel files saved here
```

---

## Troubleshooting

**`getaddrinfo failed` / DNS error**
The agent retries automatically up to 5 times with backoff. Usually a transient network blip.

**`No connection adapters were found for 'gemma4:31b-cloud/api/chat'`**
The `ollama_url` field in `agent_config.json` contained the model name instead of a URL.
Fix: set `"ollama_url": "http://localhost:11434"` and `"ollama_model": "gemma4:31b-cloud"`.

**`553 5.1.3 not a valid RFC 5321 address`**
The `complaint_to` or `report_to` field contained multiple addresses separated by ` / `.
Fix: each field should hold a single email address.

**Ollama model unavailable**
The agent falls back to keyword-based classification automatically.
Check Ollama is running: `ollama serve` and the model is pulled: `ollama list`.

**App Password rejected**
Make sure IMAP is enabled in Gmail settings and you are using the App Password (not your normal Gmail password).
