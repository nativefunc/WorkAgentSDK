from __future__ import annotations

import html
import re


def _escape_closing(text: str, tag: str) -> str:
    return re.sub(rf"</({re.escape(tag)})", r"&lt;/\1", text, flags=re.IGNORECASE)


def wrap_context(kind: str, text: str) -> str:
    return f'<context kind="{html.escape(kind, quote=True)}">\n{_escape_closing(text, "context")}\n</context>'


def wrap_web(text: str) -> str:
    return f"<untrusted_web_content>\n{_escape_closing(text, 'untrusted_web_content')}\n</untrusted_web_content>"


def wrap_external(source: str, text: str) -> str:
    return (
        f'<untrusted_content source="{html.escape(source, quote=True)}">\n'
        f"{_escape_closing(text, 'untrusted_content')}\n</untrusted_content>"
    )
