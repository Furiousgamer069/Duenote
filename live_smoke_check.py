"""Live model smoke check (uses your API key and the internet). Not part of the normal test suite.

Run:  .venv/Scripts/python.exe live_smoke_check.py
"""
import os
import sys
import time


def main():
    from dotenv import load_dotenv

    from provider import GemmaProvider, ProviderError

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    provider = GemmaProvider(overall_budget_s=120)
    started = time.monotonic()
    try:
        answer = provider.generate(["Reply with exactly: OK"])
    except ProviderError as e:
        sys.exit(f"FAILED ({e.kind}): {e.friendly}")
    print(f"Model {provider.last_model} answered in {time.monotonic() - started:.1f}s: {answer[:60]!r}")


if __name__ == "__main__":
    main()
