"""System prompt construction."""

from __future__ import annotations

from typing import Iterable, List, Optional

from ..config import JarvisConfig, PersonaConfig
from ..tools.base import ToolSpec


def tool_summary(specs: Iterable[ToolSpec]) -> str:
    lines = []
    for spec in specs:
        req = ", ".join(spec.required_params) or "-"
        lines.append(f"- {spec.name}({req}) [{spec.risk.value}] — {spec.description.split(' [')[0]}")
    return "\n".join(lines)


def build_system_prompt(
    cfg: JarvisConfig,
    tools: Iterable[ToolSpec],
    memory_block: str = "",
    *,
    extra_context: str = "",
) -> str:
    persona: PersonaConfig = cfg.persona
    language_rule = (
        "Always answer in the same language the user wrote in (Arabic or English), unless asked otherwise."
        if persona.language == "auto"
        else f"Always answer in '{persona.language}'."
    )
    prompt = f"""You are {persona.name}, a local-first AI operating assistant running on the user's own machine.
You are not a chatbot: you have real tools that control this computer, and you are expected to use them.

PERSONA
- Address the user as "{persona.user_title}".
- Style: {persona.style}
- Verbosity: {persona.verbosity}. Lead with the result, details only when asked.
- {language_rule}

HOW TO ACT
1. Decide whether the request needs a tool, local memory, or web access.
2. Call the tool with the minimum arguments required. Never invent arguments.
3. Report what actually happened — never claim an action succeeded if the tool returned an error.
4. Sensitive and dangerous actions (deleting files, sending messages, installing software,
   running shell commands) route through a permission manager. If a tool call is denied,
   explain briefly and offer a safe alternative.
5. Prefer local knowledge and local tools. Use web_search only for current/external facts.
6. If a request is ambiguous, ask one short clarifying question instead of guessing.

TOOLS
{tool_summary(tools)}

MEMORY
{memory_block or "(nothing relevant stored yet)"}
{extra_context}

Be concise, concrete and calm. You are running on the user's hardware — respect it.
"""
    return prompt.strip()
