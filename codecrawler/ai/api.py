"""Direct Anthropic API path for the 'ask' key.

Uses the official ``anthropic`` SDK (an optional dependency: install with
``pip install "codecrawler[ai]"``). Credentials are resolved by the SDK in the
usual way — ``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile — so no key is
requested here.
"""

from __future__ import annotations

from ..config import Config
from .prompt import AskPrompt


class AIUnavailable(RuntimeError):
    """Raised when the API path cannot be used (missing SDK, creds, or network)."""


def available() -> tuple[bool, str]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, 'anthropic SDK not installed — run: pip install "codecrawler[ai]"'
    return True, "ready"


def ask(cfg: Config, prompt: AskPrompt) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - guarded by available()
        raise AIUnavailable(
            'anthropic SDK not installed — run: pip install "codecrawler[ai]"'
        ) from exc

    try:
        client = anthropic.Anthropic()
    except Exception as exc:  # constructor validates credentials lazily, but be safe
        raise AIUnavailable(f"could not create Anthropic client: {exc}") from exc

    try:
        message = client.messages.create(
            model=cfg.ai.model,
            max_tokens=cfg.ai.max_tokens,
            system=prompt.system,
            messages=[{"role": "user", "content": prompt.user}],
        )
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(
            f"API error {exc.status_code}: {getattr(exc, 'message', str(exc))}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable(f"could not reach the API: {exc}") from exc
    except anthropic.AnthropicError as exc:
        raise AIUnavailable(str(exc)) from exc

    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()
