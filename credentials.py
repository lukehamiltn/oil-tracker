"""
Where the API keys come from, in one place:
  - GitHub Actions: environment variables (repository secrets)
  - your computer: the .env file (never committed)
  - Streamlit Cloud: the app's secrets
"""

import os

ALPACA = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")


def load(names: tuple[str, ...] = ALPACA) -> bool:
    """Put the keys into the environment if they aren't there yet. True if
    they're all available."""
    if not all(n in os.environ for n in names):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    if not all(n in os.environ for n in names):
        try:
            import streamlit as st
            for n in names:
                os.environ.setdefault(n, st.secrets[n])
        except Exception:
            pass
    return all(os.environ.get(n) for n in names)


def alpaca() -> tuple[str, str]:
    """(key, secret); raises KeyError if they can't be found."""
    load()
    return os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
