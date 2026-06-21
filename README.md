# Desktop Support Agent

An automated email monitoring agent that reads an inbox, classifies every new email using a local Ollama AI model (Gemma4:31b-cloud), and routes each one to the right recipient — with auto-replies, complaint tokens, and department forwarding.

---

## What It Does

```
New email arrives in sumant@ksaptech.com
              │
              ▼
    AI analyses the email
    (category + importance + complaint check)
              │
   ┌──────────┼──────────┬──────────────────┐
   │          │          │                  │
Product    HR email  Marketing /        All other
complaint             Accounting          emails
   │          │          │                  │
   ▼          ▼          ▼                  ▼
Forward    Forward    Forward          Batch into
  to         to         to           Excel report
vikas@    hr@        marketing@   → sumant.chakravarty
ksaptech  kasptech   kasptech       @gmail.com
  .com      .com       .com
   │          │          │
   └──────────┴──────────┘
              │
              ▼
   Auto-reply sent to customer
   (complaint includes tracking token)
```

### Routing logic

| Email Category | Forwarded to | Customer gets auto-reply? |
|---|---|---|
| `product_complaint` | `vikas@ksaptech.com` | Yes — includes **Complaint Token** |
| `hr` | `hr@kasptech.com` | Yes — routed to HR team |
| `marketing` | `marketing@kasptech.com` | Yes — routed to Marketing team |
| `accounting` | `accounting@kasptech.com` | Yes — routed to Accounting team |
| Everything else | — | No — included in Excel report |

### Complaint Token

Every product complaint generates a unique tracking reference (e.g. `CMP-20260621-A3F9`). The token appears:
- In the forwarded alert subject and body sent to `vikas@ksaptech.com`
- In the auto-reply sent back to the customer
- In the `Action Taken` column of the Excel decision chart

The customer can quote this token when chasing the complaint.

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
# Continuous mode (default) — polls every hour
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
| `password` | Gmail App Password | `kaaa aabc jyaw srkb` |
| `imap_host` | IMAP server | `imap.gmail.com` |
| `imap_port` | IMAP port (SSL) | `993` |
| `smtp_host` | SMTP server | `smtp.gmail.com` |
| `smtp_port` | SMTP port (TLS) | `587` |
| `complaint_to` | Product complaint forward address | `vikas@ksaptech.com` |
| `report_to` | Excel report recipient | `sumant.chakravarty@gmail.com` |
| `ollama_url` | Ollama base URL | `http://localhost:11434` |
| `ollama_model` | Model to use | `gemma4:31b-cloud` |
| `fetch_mode` | Initial fetch scope | `unread` / `last7days` / `all` |

> **Security note:** `agent_config.json` contains your App Password in plain text. Do not commit it to version control. Add it to `.gitignore`.

> **Department addresses** (`hr@kasptech.com`, `marketing@kasptech.com`, `accounting@kasptech.com`) are hardcoded in `main.py` under `DEPARTMENT_ROUTING`. Edit that dict to change them without touching any other file.

---

## Email Categories

The AI classifies every email into one of these categories:

| Category | Description | Action |
|---|---|---|
| `product_complaint` | Complaint about a product defect or dissatisfaction | Forwarded to `vikas@ksaptech.com` + complaint token reply |
| `hr` | HR-related queries (recruitment, payroll, leave, policies) | Forwarded to `hr@kasptech.com` + auto-reply |
| `marketing` | Marketing-related queries or campaigns | Forwarded to `marketing@kasptech.com` + auto-reply |
| `accounting` | Accounting, invoices, or finance queries | Forwarded to `accounting@kasptech.com` + auto-reply |
| `billing_issue` | Invoice, payment, or subscription problems | Included in Excel report |
| `technical_support` | Technical help requests | Included in Excel report |
| `feature_request` | Requests for new features | Included in Excel report |
| `general_inquiry` | General questions | Included in Excel report |
| `newsletter_or_promo` | Marketing emails and newsletters | Included in Excel report |
| `spam` | Unsolicited mail | Included in Excel report |
| `internal_communication` | Internal company emails | Included in Excel report |
| `order_status` | Order tracking and delivery | Included in Excel report |
| `feedback` | General feedback (not a complaint) | Included in Excel report |
| `other` | Anything that doesn't fit above | Included in Excel report |

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
| `agent_config.json` | Credentials and settings (keep private) |
| `processed_uids.json` | UIDs of all processed emails (prevents duplicates across restarts) |
| `reports/email_decision_chart_YYYYMMDD_HHMMSS.xlsx` | Excel report per cycle |

### Excel Report Tabs

1. **Summary** — total counts, complaint count, importance breakdown
2. **Decision Chart** — one row per email with category, importance, AI summary, action taken (complaint tokens shown here)
3. **Category Breakdown** — count and percentage per category

---

## Project Structure

```
desktopSupport_Agent/
├── main.py               Daemon loop, routing logic, CLI entry point
├── config_manager.py     First-run wizard, credential storage
├── email_handler.py      IMAP reader, SMTP sender, complaint + department forwarder
├── ai_analyzer.py        Ollama integration, keyword fallback classifier
├── excel_reporter.py     Excel decision chart builder
├── requirements.txt      Python dependencies
├── agent_config.json     Generated on first run (keep private)
├── processed_uids.json   Generated at runtime (tracks seen email UIDs)
└── reports/              Excel files saved here
```

### Key functions by file

**`main.py`**
- `DEPARTMENT_ROUTING` — dict mapping category → (display name, email address); edit here to change department addresses
- `process_cycle()` — fetches, analyses, and routes all new emails each poll

**`email_handler.py`**
- `generate_complaint_token()` — produces a unique `CMP-YYYYMMDD-XXXX` token per complaint
- `SMTPClient.forward_complaint()` — forwards product complaints with token in subject + body
- `SMTPClient.reply_to_customer()` — sends acknowledgement with complaint token to customer
- `SMTPClient.forward_to_department()` — forwards HR / Marketing / Accounting emails to the right inbox
- `SMTPClient.reply_to_customer_department()` — sends department-specific acknowledgement to customer

**`ai_analyzer.py`**
- `OllamaAnalyzer.analyse()` — calls Ollama, parses JSON response, falls back to keyword matching if model is unavailable

---

## Troubleshooting

**`getaddrinfo failed` / DNS error**
The agent retries automatically up to 5 times with backoff. Usually a transient network blip.

**`No connection adapters were found for 'gemma4:31b-cloud/api/chat'`**
The `ollama_url` field in `agent_config.json` contained the model name instead of a URL.
Fix: set `"ollama_url": "http://localhost:11434"` and `"ollama_model": "gemma4:31b-cloud"`.

**`553 5.1.3 not a valid RFC 5321 address`**
A recipient field contained multiple addresses separated by `/`.
Fix: use `,` or `;` to separate multiple addresses, or use a single address per field.

**Ollama model unavailable**
The agent falls back to keyword-based classification automatically.
Check Ollama is running: `ollama serve` and the model is pulled: `ollama list`.

**App Password rejected**
Make sure IMAP is enabled in Gmail settings and you are using the App Password (not your normal Gmail password).

**Email routed to wrong department**
The AI classification drives routing. If an email is consistently misclassified, check the `confidence` field in the Excel report. Low-confidence results may need manual review or a stronger Ollama model.
