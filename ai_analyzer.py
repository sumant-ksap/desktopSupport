"""
Email analysis via Ollama (Gemma4:31b-cloud).
Each email is classified by category, importance, and whether it is a product complaint.
"""
import json
import re
import requests
from typing import Optional

CATEGORIES = [
    "product_complaint",
    "billing_issue",
    "technical_support",
    "feature_request",
    "general_inquiry",
    "newsletter_or_promo",
    "spam",
    "internal_communication",
    "order_status",
    "feedback",
    "hr",
    "marketing",
    "accounting",
    "other",
]

IMPORTANCE_LEVELS = ["critical", "high", "medium", "low"]

SYSTEM_PROMPT = """You are an expert email triage assistant for a technology company.
Your job is to read a support email and return a structured JSON analysis.
Be concise, accurate, and consistent. Always respond with valid JSON only — no preamble, no markdown fences."""

ANALYSIS_TEMPLATE = """\
Analyse the following email and respond ONLY with a JSON object matching this exact schema:

{{
  "category": "<one of: {categories}>",
  "importance": "<one of: critical | high | medium | low>",
  "is_product_complaint": <true if the email contains a complaint specifically about a product defect, malfunction, or dissatisfaction — else false>,
  "summary": "<1-2 sentence plain-English summary of what the sender wants or is reporting>",
  "suggested_action": "<brief recommended action for the support team>",
  "confidence": "<high | medium | low — how confident you are in this classification>"
}}

EMAIL:
Subject : {subject}
From    : {sender}
Date    : {date}
---
{body}
"""


class OllamaAnalyzer:
    def __init__(self, config: dict):
        url = config.get("ollama_url", "http://localhost:11434")
        # Guard against the model name being stored in the URL field
        if not url.startswith("http://") and not url.startswith("https://"):
            print(f"[AI] WARNING: ollama_url '{url}' looks invalid — defaulting to http://localhost:11434")
            url = "http://localhost:11434"
        self._base_url = url.rstrip("/")
        self._model = config.get("ollama_model", "gemma4:31b-cloud")
        self._timeout = 120  # seconds — large model may be slow

    def _call_ollama(self, prompt: str) -> Optional[str]:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": 0.1,   # low temp for deterministic classification
                "num_predict": 512,
            },
        }
        try:
            response = requests.post(url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")
        except requests.exceptions.ConnectionError:
            print(f"[AI] ERROR: Cannot connect to Ollama at {self._base_url}.")
            print("     Make sure Ollama is running: `ollama serve`")
            return None
        except requests.exceptions.Timeout:
            print(f"[AI] ERROR: Ollama request timed out after {self._timeout}s.")
            return None
        except Exception as e:
            print(f"[AI] ERROR: {e}")
            return None

    def _parse_json(self, text: str) -> Optional[dict]:
        if not text:
            return None
        # Strip markdown code fences if the model added them
        text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
        # Extract the first JSON object we can find
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _fallback_analysis(self, subject: str, body: str) -> dict:
        """Keyword-based fallback when the model is unavailable."""
        combined = (subject + " " + body).lower()
        complaint_keywords = [
            "complaint", "broken", "defective", "not working", "issue", "problem",
            "malfunction", "faulty", "poor quality", "disappointed", "unhappy",
            "refund", "return", "damaged", "failure", "bug", "crash", "error",
        ]
        is_complaint = any(kw in combined for kw in complaint_keywords)

        spam_keywords = ["unsubscribe", "click here", "limited offer", "discount", "sale", "deal"]
        is_spam = any(kw in combined for kw in spam_keywords)

        if is_complaint:
            category = "product_complaint"
            importance = "high"
        elif is_spam:
            category = "newsletter_or_promo"
            importance = "low"
        else:
            category = "general_inquiry"
            importance = "medium"

        return {
            "category": category,
            "importance": importance,
            "is_product_complaint": is_complaint,
            "summary": f"(Fallback) {subject[:120]}",
            "suggested_action": "Review manually",
            "confidence": "low",
        }

    def analyse(self, email_data: dict) -> dict:
        prompt = ANALYSIS_TEMPLATE.format(
            categories=" | ".join(CATEGORIES),
            subject=email_data.get("subject", ""),
            sender=email_data.get("sender", ""),
            date=email_data.get("date", ""),
            body=email_data.get("body", "")[:3000],
        )

        print(f"[AI]  Analysing: {email_data.get('subject', '')[:70]} …")
        raw = self._call_ollama(prompt)
        result = self._parse_json(raw) if raw else None

        if result is None:
            print("[AI]  Model unavailable or parse error — using keyword fallback.")
            result = self._fallback_analysis(
                email_data.get("subject", ""),
                email_data.get("body", ""),
            )

        # Normalise fields
        result["category"] = result.get("category", "other").lower().replace(" ", "_")
        result["importance"] = result.get("importance", "medium").lower()
        result["is_product_complaint"] = bool(result.get("is_product_complaint", False))

        if result["category"] not in CATEGORIES:
            result["category"] = "other"
        if result["importance"] not in IMPORTANCE_LEVELS:
            result["importance"] = "medium"

        return result
