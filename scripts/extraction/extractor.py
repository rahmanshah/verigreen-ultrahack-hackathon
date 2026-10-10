"""LLM extraction of Scope 1 / Scope 2 values from the pages chosen by page_finder. One API call per PDF.

    <side env python> scripts/extraction/extractor.py estimate [key ...]      # no network: tokens + cost per call
    <side env python> scripts/extraction/extractor.py run <key> --go          # one real call, then the verifier

Before every call: count tokens (chars / 4 x margin for input, MAX_OUTPUT_TOKENS as worst-case output) and stop if
spent-so-far + worst case would exceed SPEND_CAP_EUR. A model other than config.MODEL needs --fallback-approved.
Each run writes a new folder under RAW_DIR (git-ignored), never overwriting an earlier run.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from page_finder import find_pages, page_texts  # noqa: E402

INSTRUCTIONS = f"""You extract greenhouse-gas figures from pages of a company report.
Return one record for every combination of scope in {list(config.SCOPES)} and year in {list(config.TARGET_YEARS)}.
Scopes: "1" = Scope 1 (gross); "2_location" = Scope 2 location-based; "2_market" = Scope 2 market-based.

Rules:
- Copy values only. Never infer, estimate, sum, convert or calculate a value. If the exact figure for a scope and
  year is not printed on the supplied pages, set value, unit_as_printed, pdf_page and quote to null and give a short
  null_reason.
- If a Scope 2 figure does not state whether it is location-based or market-based, do not assign it: return null
  with that reason.
- value: the number exactly as printed, as a plain number (keep its decimal places; drop thousands separators).
- unit_as_printed: the unit exactly as printed for that figure (for example from the table header).
- pdf_page: the number in the "=== PDF page index N ===" marker of the page the figure is on. Not the printed page
  number.
- quote: a short verbatim span copied character for character from that page that contains the figure (for a table,
  the row label and the cells as they appear in the text). Do not fix spacing, spelling or line order.
- note: boundary or method information stated next to the figure (for example restated, excludes discontinued
  operations, biogenic CO2 reported separately); null if none is stated.
"""

RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["records"],
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["company", "scope", "year", "value", "unit_as_printed", "pdf_page", "quote", "note",
                             "null_reason"],
                "properties": {
                    "company": {"type": "string"},
                    "scope": {"type": "string", "enum": list(config.SCOPES)},
                    "year": {"type": "integer"},
                    "value": {"type": ["number", "null"]},
                    "unit_as_printed": {"type": ["string", "null"]},
                    "pdf_page": {"type": ["integer", "null"]},
                    "quote": {"type": ["string", "null"]},
                    "note": {"type": ["string", "null"]},
                    "null_reason": {"type": ["string", "null"]},
                },
            },
        }
    },
}


def build_input(key: str) -> tuple[str, list[int], dict[int, str]]:
    fname, company = config.PDFS[key]
    texts = page_texts(config.PDF_DIR / fname)
    sent = find_pages(texts)
    body = "\n\n".join(f"=== PDF page index {n} ===\n{texts[n]}" for n in sent)
    return f"Company: {company}\nReport file: {fname}\n\n{body}", sent, texts


def estimate(key: str, model: str) -> dict:
    user, sent, _ = build_input(key)
    chars = len(INSTRUCTIONS) + len(user) + len(json.dumps(RECORD_SCHEMA))
    in_tok = round(chars / 4 * config.TOKEN_ESTIMATE_MARGIN)
    worst = cost_eur(model, in_tok, config.MAX_OUTPUT_TOKENS)
    return {"key": key, "model": model, "sent_pages": sent, "chars": chars, "input_tokens_est": in_tok,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS, "worst_case_eur": worst}


def cost_eur(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = config.PRICES_USD[model]
    return (input_tokens * p_in + output_tokens * p_out) / 1e6 * config.USD_TO_EUR


def spent_eur() -> float:
    """Recomputed from the ledger's actual token counts at current prices (so earlier entries priced at the old
    input rate are counted at the cache-write rate too)."""
    if not config.LEDGER.exists():
        return 0.0
    entries = [json.loads(line) for line in config.LEDGER.read_text(encoding="utf-8").splitlines() if line]
    return sum(cost_eur(e["model"], e["input_tokens"], e["output_tokens"]) for e in entries)


def print_estimate(e: dict) -> None:
    print(f"{e['key']:<15} {e['model']:<12} pages {e['sent_pages']}  chars {e['chars']:>6}  "
          f"input est {e['input_tokens_est']:>6} tok (x{config.TOKEN_ESTIMATE_MARGIN})  "
          f"output max {e['max_output_tokens']} tok  worst case EUR {e['worst_case_eur']:.4f}")


def run(key: str, model: str) -> Path:
    e = estimate(key, model)
    spent = spent_eur()
    print_estimate(e)
    print(f"spent so far EUR {spent:.4f}, cap EUR {config.SPEND_CAP_EUR:.2f}")
    if spent + e["worst_case_eur"] > config.SPEND_CAP_EUR:
        sys.exit(f"STOP: spent + worst case = EUR {spent + e['worst_case_eur']:.4f} exceeds the cap. Ask Shah.")

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(config.REPO / ".env")
    if not os.environ.get(config.API_KEY_ENV):
        sys.exit(f"{config.API_KEY_ENV} not set in .env")
    # max_retries=0: the SDK retries twice by default; this spike makes exactly one attempt per call
    client = OpenAI(base_url=config.BASE_URL, api_key=os.environ[config.API_KEY_ENV], max_retries=0, timeout=300)

    user, sent, _ = build_input(key)
    params = {"model": model, "instructions": INSTRUCTIONS, "input": user, "store": False,
              "max_output_tokens": config.MAX_OUTPUT_TOKENS,
              "text": {"format": {"type": "json_schema", "name": "ghg_records", "schema": RECORD_SCHEMA,
                                  "strict": True}}}
    if config.REASONING_EFFORT is not None:
        params["reasoning"] = {"effort": config.REASONING_EFFORT}
    if config.TEMPERATURE is not None:
        params["temperature"] = config.TEMPERATURE

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.RAW_DIR / f"{stamp}_{key}_{model}"
    run_dir.mkdir(parents=True, exist_ok=False)
    meta = {"pdf": config.PDFS[key][0], "company": config.PDFS[key][1], "sent_pages": sent, "provider": config.PROVIDER,
            "base_url": config.BASE_URL, "model": model, "reasoning_effort": config.REASONING_EFFORT,
            "temperature": config.TEMPERATURE, "estimate": e, "started_utc": stamp}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run_dir / "prompt.txt").write_text(f"[instructions]\n{INSTRUCTIONS}\n[input]\n{user}\n", encoding="utf-8")

    t0 = time.perf_counter()
    resp = client.responses.create(**params)
    latency_s = time.perf_counter() - t0
    (run_dir / "response_raw.json").write_text(resp.model_dump_json(indent=2), encoding="utf-8")

    u = resp.usage
    cost = cost_eur(model, u.input_tokens, u.output_tokens)
    entry = {"run": run_dir.name, "model": model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "reasoning_tokens": getattr(u.output_tokens_details, "reasoning_tokens", None), "cost_eur": cost,
             "latency_s": round(latency_s, 2), "status": resp.status}
    with config.LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"usage: {entry}; spent now EUR {spent + cost:.4f}")

    if resp.status != "completed":
        sys.exit(f"response status {resp.status} ({resp.incomplete_details}); raw saved in {run_dir}, not parsed")
    try:
        parsed = json.loads(resp.output_text)
    except json.JSONDecodeError as err:
        sys.exit(f"invalid JSON ({err}); raw saved in {run_dir}, not parsed, no retry")
    (run_dir / "records.json").write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    return run_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["estimate", "run"])
    ap.add_argument("keys", nargs="*", default=list(config.PDFS))
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--go", action="store_true", help="required for a real API call")
    ap.add_argument("--fallback-approved", action="store_true", help="required for any model other than config.MODEL")
    a = ap.parse_args()

    if a.mode == "estimate":
        es = [estimate(k, a.model) for k in a.keys]
        for e in es:
            print_estimate(e)
        print(f"total worst case EUR {sum(e['worst_case_eur'] for e in es):.4f}; spent so far EUR {spent_eur():.4f}")
        return
    if not a.go or len(a.keys) != 1:
        sys.exit("run needs exactly one key and --go")
    if a.model != config.MODEL and not a.fallback_approved:
        sys.exit(f"{a.model} needs --fallback-approved (Shah's approval)")
    run_dir = run(a.keys[0], a.model)
    import verifier
    verifier.main(run_dir)


if __name__ == "__main__":
    main()
