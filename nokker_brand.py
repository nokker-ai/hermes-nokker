"""Nokker brand layer — the only place that knows the product is called Nokker.

Hermes Agent (upstream, ``vendor/hermes``) names itself everywhere: ~230 "hermes setup" hints, ~680
files citing ``hermes <cmd>``. Rewriting them would make every quarterly rebase a conflict storm, so the
fork keeps the upstream text and rewrites it at a handful of choke points (each one tagged
``# nokker-brand`` in the upstream file, list in ``docs/BRAND.md``):

* ``rebrand_text(s)`` rewrites what a *human* reads: command hints (``hermes setup tts`` ->
  ``nokker setup tts``), the product name (``Hermes Agent`` -> ``Nokker``) and the upstream docs URL.
* ``prose=True`` additionally renames a bare ``Hermes`` used as the product name in prose. Only for
  text that upstream authored as product copy (prompt stable tier, UI catalog, the bundled
  ``hermes-agent`` skill), never for arbitrary tool output.

What is never touched, by construction of the patterns below: paths and dotfiles (``/opt/hermes``,
``~/.hermes``, ``.hermes.md``), module and package names (``hermes_cli.main``, ``hermes-agent``),
environment variables (``HERMES_HOME``: upper case), the ``hermes`` system user (``s6-setuidgid
hermes``, ``--user hermes``) and any identifier glued to ``_ . / - \\ ~ $ @``.

Switch: ``NOKKER_BRAND=0`` (read once at import) turns the whole layer into a pass-through and gives back
pure upstream behaviour — for diagnosis, and for the upstream test suite (``tests/conftest.py`` sets it, so
upstream assertions on "hermes …" copy keep passing untouched; ``tests/test_nokker_brand.py`` re-enables it).

Stdlib only and import-safe.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import re
from typing import Any

ENABLED = os.environ.get("NOKKER_BRAND", "1").strip().lower() not in {"0", "false", "no", "off"}

PRODUCT_NAME = "Nokker"
CLI_NAME = "nokker"
LEGACY_CLI_NAME = "hermes"  # still installed, silent alias (scripts, s6 services, muscle memory)
SITE_URL = "https://nokker.ai"
DOCS_URL = f"{SITE_URL}/docs"  # page not live yet; one constant to move when it is
UPSTREAM_DOCS_URL = "https://hermes-agent.nousresearch.com/docs"
HOME_ENV = "NOKKER_HOME"
LEGACY_HOME_ENV = "HERMES_HOME"

# The bundled skill the prompt tells the model to load for self-help. Its content is upstream's and
# is rebranded in prose mode when skill_view returns it (see rebrand_tool_result).
SELF_HELP_SKILL = "hermes-agent"

# Top-level CLI verbs. ``hermes <verb>`` is only rewritten when <verb> is one of these (or a flag), so
# prose such as "the hermes user" or "hermes is a Greek god" stays as written. Source:
# ``hermes_cli.main._build_cli_parser()`` on v0.22.2 (75 verbs) + verbs dispatched outside argparse.
# tests/test_nokker_brand.py fails when upstream adds a verb that is missing here.
CLI_SUBCOMMANDS = frozenset("""
acp approvals auth backup browser bundles chat checkpoints claw codex-runtime completion computer-use
config connectors console cron curator dashboard debug desktop doctor dump egress fallback gateway gui
hooks import import-agent insights journey kanban learning login logout logs lsp mcp memory
memory-graph migrate moa model monitoring pairing pause peer pets plugins portal profile project
prompt-size proxy resume secrets security send serve sessions setup skills skin slack status tools
uninstall update usage vault verify webhook whatsapp whatsapp-cloud worktree
pm version honcho spotify
""".split())


# Characters that, glued in front of "hermes", mean it is part of a path / identifier / address.
_NOT_AFTER = r"(?<![\w./\\~$@:-])"
_SUBCOMMAND_ALT = "|".join(sorted((re.escape(c) for c in CLI_SUBCOMMANDS), key=len, reverse=True))

_DOCS_RE = re.compile(r"https?://hermes-agent\.nousresearch\.com/docs")
_SITE_RE = re.compile(r"https?://hermes-agent\.nousresearch\.com(?![\w.-])")
# "Hermes Agent", with the upstream attribution folded in so the result reads "You are Nokker."
_AGENT_RE = re.compile(
    _NOT_AFTER + r"Hermes Agent(?:,? (?:built )?by Nous Research| ?\((?:built )?by Nous Research\))?(?![\w-])"
)
# `hermes <verb>` / `hermes --flag` / `hermes -p` / `hermes <command>` / `hermes [opts]` as a command line a
# human would type (whitespace may be a line wrap), or a bare `hermes` heading a help-table row.
_CMD_RE = re.compile(
    _NOT_AFTER + r"hermes(?=\s+(?:(?:" + _SUBCOMMAND_ALT + r")(?![\w-])|--?[A-Za-z]|<\w|\[)|[ \t]{2,}\S)"
)
# The bare command, quoted: `hermes`, 'hermes', "hermes".
_QUOTED_RE = re.compile(r"(?<=[`'\"])hermes(?=[`'\"])")
# Prose: a bare product-name "Hermes" (not Hermes_x, Hermes/x, Hermes-x, Hermes.x).
_PROSE_RE = re.compile(_NOT_AFTER + r"Hermes(?![\w/\\-])(?!\.\w)")
# Attribution left dangling after the name swap ("Nokker is ... by Nous Research").
_ATTRIBUTION_RE = re.compile(r"(\bNokker\b[^.\n]*?) by Nous Research")
_ATTRIBUTION = " by Ninabot (MIT fork of the Nous Research agent)"


def rebrand_text(s: Any, *, prose: bool = False) -> Any:
    """Rewrite human-facing upstream branding in ``s``; non-strings are returned unchanged.

    Idempotent, deterministic (safe on cached prompt prefixes) and a no-op on text that does not
    contain "ermes" or "nousresearch" (fast path for every outbound message and tool result).
    """
    if not ENABLED or not isinstance(s, str) or not s:
        return s
    if "ermes" not in s and "nousresearch" not in s:
        return s
    out = _DOCS_RE.sub(DOCS_URL, s)
    out = _SITE_RE.sub(SITE_URL, out)
    out = _AGENT_RE.sub(PRODUCT_NAME, out)
    out = _CMD_RE.sub(CLI_NAME, out)
    out = _QUOTED_RE.sub(CLI_NAME, out)
    if prose:
        out = _PROSE_RE.sub(PRODUCT_NAME, out)
        out = _ATTRIBUTION_RE.sub(lambda m: m.group(1) + _ATTRIBUTION, out)
    return out


def rebrand_catalog(catalog: dict) -> dict:
    """UI string catalog (i18n): product copy, so prose mode. Returns a new dict."""
    if not ENABLED:
        return catalog
    return {k: rebrand_text(v, prose=True) for k, v in catalog.items()}


# Keys of a JSON tool result that carry a message for a human (or for the model to relay to one).
# Payload keys (output, content, stdout, diff, text…) are deliberately absent: rewriting a file the
# model just read would make its next patch miss.
_HINT_KEYS = frozenset({
    "error", "errors", "message", "hint", "hints", "help", "suggestion", "suggestions", "detail",
    "details", "reason", "note", "notes", "warning", "warnings", "remedy", "fix", "next_step",
    "next_steps", "usage_hint", "setup_hint", "install_hint", "instructions", "action_required",
})


def _rebrand_hint_value(value: Any) -> Any:
    if isinstance(value, str):
        return rebrand_text(value)
    if isinstance(value, list):
        return [_rebrand_hint_value(v) for v in value]
    if isinstance(value, dict):  # {"error": {"message": ..., "code": ...}}
        return {k: _rebrand_hint_value(v) if k in _HINT_KEYS or k == "message" else v for k, v in value.items()}
    return value


def rebrand_tool_result(result: Any, *, function_name: str = "", is_error: bool = False) -> Any:
    """Rebrand the human-facing fields of a tool result before it enters the model context.

    * JSON object string: only ``_HINT_KEYS`` values (recursively inside them); re-serialized only
      when something changed.
    * ``skill_view`` of the self-help skill: ``content``/``description`` in prose mode too.
    * plain string: rewritten only when the call failed (an error message, not a payload).
    * anything else (multimodal dicts…): unchanged.
    """
    if not ENABLED or not isinstance(result, str) or ("ermes" not in result and "nousresearch" not in result):
        return result
    stripped = result.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(result)
        except ValueError:
            data = None
        if isinstance(data, dict):
            new = {k: _rebrand_hint_value(v) if k in _HINT_KEYS else v for k, v in data.items()}
            if function_name == "skill_view" and data.get("name") == SELF_HELP_SKILL:
                for key in ("content", "description"):
                    new[key] = rebrand_text(data.get(key), prose=True)
            return result if new == data else json.dumps(new, ensure_ascii=False)
    return rebrand_text(result) if is_error else result


# --- gateway: every adapter's outbound text ---------------------------------------------------

# method name -> index of ``content`` in the positional args (self excluded)
_OUTBOUND_METHODS = {"send": 1, "edit_message": 2, "send_draft": 2}


def wrap_outbound_methods(cls: type) -> None:
    """Wrap the outbound text methods a platform adapter class defines so ``content`` is rebranded.

    Called from ``BasePlatformAdapter.__init_subclass__``: covers every adapter, bundled or plugin,
    without touching any of them. Idempotent (a wrapped method is marked) and transparent to
    ``super().send(...)`` chains since ``rebrand_text`` is idempotent.
    """
    for name, pos in _OUTBOUND_METHODS.items():
        fn = cls.__dict__.get(name)
        if fn is None or getattr(fn, "_nokker_brand", False) or not inspect.iscoroutinefunction(fn):
            continue  # absent, already wrapped, or not an async method (left alone rather than broken)

        def _make(fn=fn, pos=pos):
            @functools.wraps(fn)
            async def wrapper(self, *args, **kwargs):
                if "content" in kwargs:
                    kwargs["content"] = rebrand_text(kwargs["content"])
                elif len(args) > pos:
                    args = (*args[:pos], rebrand_text(args[pos]), *args[pos + 1:])
                return await fn(self, *args, **kwargs)
            wrapper._nokker_brand = True
            return wrapper

        setattr(cls, name, _make())


# --- process environment ----------------------------------------------------------------------
# NOKKER_HOME -> HERMES_HOME alias lives inline in hermes_constants.py (that module is copied standalone
# into the image's pm build stage and must not import anything outside the stdlib).

# --- CLI console --------------------------------------------------------------------------------

def rebranding(fn):
    """Decorator: rebrand the string a display helper returns (banner version label…)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return rebrand_text(fn(*args, **kwargs))
    return wrapper


SKIN_BRANDING = {
    "agent_name": PRODUCT_NAME,
    "welcome": f"Welcome to {PRODUCT_NAME}! Type your message or /help for commands.",
    "goodbye": "Goodbye! ◎",
    "response_label": f" ◎ {PRODUCT_NAME} ",
}

BANNER_LOGO = """[bold #FFD700]███╗   ██╗ ██████╗ ██╗  ██╗██╗  ██╗███████╗██████╗ [/]
[bold #FFD700]████╗  ██║██╔═══██╗██║ ██╔╝██║ ██╔╝██╔════╝██╔══██╗[/]
[#FFBF00]██╔██╗ ██║██║   ██║█████╔╝ █████╔╝ █████╗  ██████╔╝[/]
[#FFBF00]██║╚██╗██║██║   ██║██╔═██╗ ██╔═██╗ ██╔══╝  ██╔══██╗[/]
[#CD7F32]██║ ╚████║╚██████╔╝██║  ██╗██║  ██╗███████╗██║  ██║[/]
[#CD7F32]╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝[/]"""

# Door knocker: plate, ring hanging from it.
BANNER_HERO = """[#CD7F32]      ▄▄████▄▄      [/]
[#CD7F32]    ▄██▀▀▀▀▀▀██▄    [/]
[#FFBF00]   ██  ◉    ◉  ██   [/]
[#FFBF00]   ██    ▄▄    ██   [/]
[#FFD700]    ▀██▄▀▀▀▀▄██▀    [/]
[#FFD700]      ▄▀▀██▀▀▄      [/]
[#FFBF00]     █   ██   █     [/]
[#FFBF00]     █        █     [/]
[#CD7F32]      ▀▄    ▄▀      [/]
[#B8860B]        ▀▀▀▀        [/]"""


def cli_name() -> str:
    """The command name shown to the user (argparse ``prog``)."""
    return CLI_NAME if ENABLED else LEGACY_CLI_NAME


def skin_branding() -> dict:
    """Branding overrides for the Hermes-named built-in skins ({} when the layer is off)."""
    return dict(SKIN_BRANDING) if ENABLED else {}


def banner_art(logo: str, hero: str) -> tuple:
    """(logo, hero) for the CLI banner: Nokker's when the layer is on, upstream's otherwise."""
    return (BANNER_LOGO, BANNER_HERO) if ENABLED else (logo, hero)


def legacy_prog(prog: str) -> str:
    """``nokker auth`` -> ``hermes auth``: upstream helpers compare argparse ``prog`` to the old name."""
    if prog == CLI_NAME or prog.startswith(CLI_NAME + " "):
        return LEGACY_CLI_NAME + prog[len(CLI_NAME):]
    return prog
