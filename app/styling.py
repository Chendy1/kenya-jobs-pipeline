"""Shared visual layer: one theme, injected once. No data logic here."""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
:root {
    --kj-green: #0B6E4F;
    --kj-green-dark: #084d38;
    --kj-amber: #B8860B;
    --kj-red: #B3261E;
    --kj-ink: #16211C;
    --kj-card: #F3F6F4;
}

/* header band */
.kj-header {
    background: linear-gradient(135deg, var(--kj-green) 0%, var(--kj-green-dark) 100%);
    color: white;
    padding: 1.4rem 1.6rem;
    border-radius: 12px;
    margin-bottom: 1.2rem;
}
.kj-header h1 { color: white; margin: 0 0 0.2rem 0; font-size: 1.7rem; }
.kj-header p { color: #E5F0EC; margin: 0; font-size: 0.95rem; }

/* metric cards */
div[data-testid="stMetric"] {
    background: var(--kj-card);
    border: 1px solid #E1E8E4;
    border-radius: 10px;
    padding: 0.9rem 1rem 0.7rem 1rem;
}
div[data-testid="stMetricLabel"] { color: #4A5D54; font-weight: 500; }
div[data-testid="stMetricValue"] { color: var(--kj-green-dark); }

/* tabs */
button[data-baseweb="tab"] { font-weight: 600; }

/* pill badges */
.kj-pill {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    margin-right: 0.3rem;
    white-space: nowrap;
}
.kj-pill-green  { background: #E4F3EC; color: var(--kj-green-dark); }
.kj-pill-amber  { background: #FBF0DA; color: #7A5A05; }
.kj-pill-red    { background: #FBE9E7; color: var(--kj-red); }
.kj-pill-grey   { background: #EDEFEE; color: #4A5D54; }

/* empty state */
.kj-empty {
    text-align: center;
    padding: 2.5rem 1rem;
    color: #6B7C73;
}
.kj-empty .kj-emoji { font-size: 2.2rem; display: block; margin-bottom: 0.4rem; }
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="kj-header"><h1>{title}</h1><p>{subtitle}</p></div>',
               unsafe_allow_html=True)


def status_pill(text: str, kind: str = "grey") -> str:
    """kind: green | amber | red | grey. Returns HTML, doesn't render it."""
    return f'<span class="kj-pill kj-pill-{kind}">{text}</span>'


def pill_for_status(status: str) -> str:
    return {"ok": status_pill("OK", "green"), "warnings": status_pill("WARNINGS", "amber"),
           "failed": status_pill("FAILED", "red"), "crashed": status_pill("CRASHED", "red")}.get(
        status, status_pill(status.upper(), "grey"))


def empty_state(emoji: str, message: str) -> None:
    st.markdown(f'<div class="kj-empty"><span class="kj-emoji">{emoji}</span>{message}</div>',
               unsafe_allow_html=True)