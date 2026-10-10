"""Single config for the LLM extraction spike. Provider, model, base URL and limits live here only.

Runs in the side env C:\\Users\\Shah\\venvs\\verigreen-extract (pymupdf, openai, python-dotenv), not the project env.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# --- Provider ---------------------------------------------------------------------------------------------------
PROVIDER = "openai"
BASE_URL = "https://api.openai.com/v1"
API_KEY_ENV = "OPENAI_API_KEY"  # read from REPO / ".env" via python-dotenv, never printed
MODEL = "gpt-6-luna"
FALLBACK_MODEL = "gpt-6.1-sol"  # only with Shah's explicit approval (pass --model on the command line)

# USD per 1M tokens (input, output), from OpenAI's pricing page as given by Shah. Reasoning tokens bill as output.
# All input is priced at the cache-write rate (the first Outokumpu call wrote 5,311 of 5,314 input tokens to the
# cache), in the ledger and in the pre-call worst case. gpt-6-luna cache write $0.125 is from its model page;
# gpt-6.1-sol cache write $2.50 per 1M (vs $2.00 input) is verified from the pricing page; Sol was not used.
PRICES_USD = {"gpt-6-luna": (0.125, 0.50), "gpt-6.1-sol": (2.50, 10.00)}

# Request settings. None = not sent.
# temperature: not documented for gpt-6-luna on its model page -> not sent.
# reasoning.effort: documented values none/low/medium(default)/high/xhigh/max.
TEMPERATURE = None
REASONING_EFFORT = "low"
MAX_OUTPUT_TOKENS = 8000  # hard upper bound per call, includes reasoning tokens; used as worst case in cost checks

# --- Spend cap ----------------------------------------------------------------------------------------------------
SPEND_CAP_EUR = 5.00
# Prices are in USD. Treat 1 USD as 1 EUR: overstates EUR cost while USD < EUR, so the cap check stays conservative.
USD_TO_EUR = 1.00
# Pre-call input estimate = chars / 4 x this margin (number-heavy tables tokenise worse than prose).
TOKEN_ESTIMATE_MARGIN = 2.0

# --- Inputs -------------------------------------------------------------------------------------------------------
PDF_DIR = REPO / "data" / "raw_pdfs"
PDFS = {  # key -> (file, company label used in the prompt)
    "outokumpu_2025": ("Outokumpu_Sustainability_Statement_2025.pdf", "Outokumpu"),
    "orion_2025": ("orion-financial-statement-documents-2025.pdf", "Orion"),
    "elisa_2025": ("Elisa_AnnualReport_2025.pdf", "Elisa"),
}
TARGET_YEARS = (2023, 2024, 2025)
SCOPES = ("1", "2_location", "2_market")

# Page finder. Page numbers everywhere are 1-based PDF page indexes, not printed page numbers.
PAGE_CAP = 4
LOW_TEXT_CHARS = 300

# --- Outputs ------------------------------------------------------------------------------------------------------
RAW_DIR = REPO / "data" / "extraction" / "raw_responses"  # git-ignored (.gitignore)
LEDGER = RAW_DIR / "spend_ledger.jsonl"
