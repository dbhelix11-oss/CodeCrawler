"""On-demand explanations from Claude: a shared prompt builder plus two delivery
paths — a copy/paste 'bridge' and a direct Anthropic API call.
"""

from .prompt import AskPrompt, ParsedAnswer, build_prompt, parse_answer

__all__ = ["AskPrompt", "ParsedAnswer", "build_prompt", "parse_answer"]
