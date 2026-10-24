"""Nokker brand layer (nokker_brand.py): rewrite rules and every choke point that uses them.

tests/conftest.py runs the upstream suite with NOKKER_BRAND=0; this module turns the layer back on
(``ENABLED`` for call-time hooks, a ``NOKKER_BRAND=1`` subprocess for import-time ones).
"""

import asyncio
import inspect
import json

import pytest

import nokker_brand as nb
from nokker_brand import rebrand_text as rb


@pytest.fixture(autouse=True)
def _brand_on(monkeypatch):
    monkeypatch.setattr(nb, "ENABLED", True)


def _branded_subprocess(code: str, tmp_path) -> dict:
    """Run *code* (must print one JSON line) in a fresh interpreter with the layer on."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "NOKKER_BRAND": "1", "HERMES_HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          cwd=os.path.dirname(nb.__file__), timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_switch_off_is_pure_passthrough(monkeypatch):
    monkeypatch.setattr(nb, "ENABLED", False)
    assert rb("run 'hermes setup tts'", prose=True) == "run 'hermes setup tts'"
    raw = '{"error": "run hermes setup"}'
    assert nb.rebrand_tool_result(raw, is_error=True) is raw
    cat = {"k": "hermes setup"}
    assert nb.rebrand_catalog(cat) is cat
    assert nb.cli_name() == "hermes" and nb.skin_branding() == {}
    assert nb.banner_art("L", "H") == ("L", "H")


# ── rebrand_text: positive cases ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("src, want", [
    # the real Telegram incident (tools/tts_tool.py) and its siblings
    ("Run 'hermes setup tts' and choose KittenTTS.", "Run 'nokker setup tts' and choose KittenTTS."),
    ("Run hermes setup tts and choose NeuTTS; espeak-ng is also required.",
     "Run nokker setup tts and choose NeuTTS; espeak-ng is also required."),
    ("Run `hermes setup` to install Mistral support.", "Run `nokker setup` to install Mistral support."),
    ("Run 'hermes tools' and select Piper under TTS.", "Run 'nokker tools' and select Piper under TTS."),
    ("hermes gateway run", "nokker gateway run"),
    ("hermes claw migrate --dry-run", "nokker claw migrate --dry-run"),
    ("try hermes doctor --fix", "try nokker doctor --fix"),
    ("hermes pm install ffmpeg", "nokker pm install ffmpeg"),
    ("hermes whatsapp-cloud", "nokker whatsapp-cloud"),
    ("hermes -p work gateway run", "nokker -p work gateway run"),
    ("hermes --tui", "nokker --tui"),
    ("Run `hermes --help` to see all commands.", "Run `nokker --help` to see all commands."),
    ("Run `hermes` to start.", "Run `nokker` to start."),
    ('use "hermes" or "hermes chat"', 'use "nokker" or "nokker chat"'),
    ("(hermes model)", "(nokker model)"),
    ("first:\n  hermes setup\nthen", "first:\n  nokker setup\nthen"),
    ("hermes setup && hermes gateway start", "nokker setup && nokker gateway start"),
    ("usage: hermes setup [-h]", "usage: nokker setup [-h]"),
    ("    hermes                        Start interactive chat", "    nokker                        Start interactive chat"),
    ("    hermes <command> --help", "    nokker <command> --help"),
    ("Usage: hermes [options]", "Usage: nokker [options]"),
    ("Without this flag, 'hermes\n                        version' exits", "Without this flag, 'nokker\n                        version' exits"),
    # product name and attribution
    ("You are Hermes Agent, built by Nous Research. Be direct.", "You are Nokker. Be direct."),
    ("You run on Hermes Agent (by Nous Research). When", "You run on Nokker. When"),
    ("Show Hermes Agent version", "Show Nokker version"),
    ("Hermes Agent's memory", "Nokker's memory"),
    # docs
    ("see https://hermes-agent.nousresearch.com/docs/user-guide/tts",
     f"see {nb.DOCS_URL}/user-guide/tts"),
    ("https://hermes-agent.nousresearch.com", nb.SITE_URL),
])
def test_rebrand_positive(src, want):
    assert rb(src) == want


@pytest.mark.parametrize("src, want", [
    ("When the user needs help with Hermes itself", "When the user needs help with Nokker itself"),
    ("troubleshooting Hermes so you don't guess", "troubleshooting Nokker so you don't guess"),
    ("Restart Hermes.", "Restart Nokker."),
    ("Hermes's scratch dir", "Nokker's scratch dir"),
    ("Hermes Agent is an open-source AI agent framework by Nous Research that runs",
     "Nokker is an open-source AI agent framework by Ninabot (MIT fork of the Nous Research agent) that runs"),
])
def test_rebrand_prose(src, want):
    assert rb(src, prose=True) == want


# ── rebrand_text: negative cases (must stay byte-identical) ────────────────────────────────────

@pytest.mark.parametrize("src", [
    "/opt/hermes/bin/hermes setup",          # path, and the binary it names
    "~/.hermes/config.yaml",
    "$HERMES_HOME/skills and HERMES_REDACT_SECRETS=1",
    "python -m hermes_cli.main setup",
    "from hermes_cli.config import load_config",
    "pip install hermes-agent",
    "load it with skill_view(name='hermes-agent')",
    "The `hermes-agent` skill",
    ".hermes.md / HERMES.md",
    "s6-setuidgid hermes python3 /x.py",     # system user name
    "docker exec --user hermes c",
    "the hermes user owns /opt/data",
    "hermes is a Greek god",
    "hermes\nis the user",
    "the [hermes] tag",
    "git@github.com:NousResearch/hermes-agent.git",
    "https://github.com/NousResearch/hermes-agent/releases",
    "/tmp/hermes-runtime",
    "C:\\Users\\x\\hermes setup",
    "hermes_tools import x",
    "data-hermes-send=\"prompt\"",
    "nothing to see here",
    "",
])
def test_rebrand_negative(src):
    assert rb(src) == src
    assert rb(src, prose=True) == src


@pytest.mark.parametrize("src", [
    "Hermes_x", "Hermes/plans", "Hermes-native", "Hermes.app", "HERMES", "hermes",
])
def test_prose_leaves_identifiers(src):
    assert rb(src, prose=True) == src


def test_non_strings_pass_through():
    for v in (None, 3, b"hermes setup", ["hermes setup"]):
        assert rb(v) is v


@pytest.mark.parametrize("src", [
    "Run 'hermes setup tts'", "You are Hermes Agent, built by Nous Research.",
    "Hermes Agent is a framework by Nous Research.", f"{nb.UPSTREAM_DOCS_URL}/x",
])
def test_idempotent(src):
    once = rb(src, prose=True)
    assert rb(once, prose=True) == once


def test_subcommands_cover_the_real_parser(monkeypatch, tmp_path):
    """Upstream adds a CLI verb -> CLI_SUBCOMMANDS must learn it, or its hints keep saying hermes."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli.main import _build_cli_parser
    _parser, subparsers = _build_cli_parser()[:2]
    missing = set(subparsers.choices) - nb.CLI_SUBCOMMANDS
    assert not missing, f"add to nokker_brand.CLI_SUBCOMMANDS: {sorted(missing)}"


# ── tool results ─────────────────────────────────────────────────────────────────────────────

def test_tool_result_tts_error_real_payload():
    from tools.tts_tool import _BUILTIN_DISPATCH, _error_json
    raw = _error_json(_BUILTIN_DISPATCH["kittentts"][3])
    assert "hermes setup tts" in raw
    out = nb.rebrand_tool_result(raw, function_name="text_to_speech", is_error=True)
    assert "nokker setup tts" in out and "hermes" not in out
    assert json.loads(out)["success"] is False


def test_tool_result_payload_keys_untouched():
    raw = json.dumps({"output": "hermes setup\n", "content": "run hermes setup", "error": "run 'hermes doctor'"})
    data = json.loads(nb.rebrand_tool_result(raw, function_name="terminal"))
    assert data["output"] == "hermes setup\n"            # a file / command output is data
    assert data["content"] == "run hermes setup"
    assert data["error"] == "run 'nokker doctor'"


def test_tool_result_nested_and_lists():
    raw = json.dumps({"error": {"message": "hermes auth login", "code": 7}, "hints": ["hermes mcp test x"]})
    data = json.loads(nb.rebrand_tool_result(raw))
    assert data == {"error": {"message": "nokker auth login", "code": 7}, "hints": ["nokker mcp test x"]}


def test_tool_result_unchanged_is_same_object():
    raw = '{"output":  "hermes setup"}'  # odd spacing must survive: no re-serialization when nothing changed
    assert nb.rebrand_tool_result(raw) is raw
    assert nb.rebrand_tool_result("cat said: hermes setup") == "cat said: hermes setup"  # success, plain
    assert nb.rebrand_tool_result("Error: run hermes setup", is_error=True) == "Error: run nokker setup"
    payload = {"content": [{"type": "text", "text": "hermes setup"}]}
    assert nb.rebrand_tool_result(payload) is payload


def test_tool_result_self_help_skill_prose():
    raw = json.dumps({"success": True, "name": "hermes-agent", "description": "Use and configure Hermes Agent.",
                      "content": "Hermes works with any provider. Run `hermes setup`.", "path": "x/hermes-agent/SKILL.md"})
    data = json.loads(nb.rebrand_tool_result(raw, function_name="skill_view"))
    assert data["content"] == "Nokker works with any provider. Run `nokker setup`."
    assert data["description"] == "Use and configure Nokker."
    assert data["name"] == "hermes-agent" and data["path"] == "x/hermes-agent/SKILL.md"
    other = json.dumps({"name": "notes", "content": "Hermes works"})
    assert json.loads(nb.rebrand_tool_result(other, function_name="skill_view"))["content"] == "Hermes works"


def test_commit_tool_result_hook_is_wired():
    import inspect
    from agent import tool_executor
    assert "rebrand_tool_result" in inspect.getsource(tool_executor._commit_tool_result)


# ── gateway outbound ─────────────────────────────────────────────────────────────────────────

def test_gateway_adapter_send_and_edit_are_rebranded():
    from gateway.platforms.base import BasePlatformAdapter

    sent = []

    class Fake(BasePlatformAdapter):
        async def connect(self): return True
        async def disconnect(self): return None
        async def get_chat_info(self, chat_id): return {}
        async def send(self, chat_id, content, reply_to=None, metadata=None):
            sent.append(content)
        async def edit_message(self, chat_id, message_id, content, *, finalize=False):
            sent.append(content)

    class Sub(Fake):  # super().send chain stays idempotent
        async def send(self, chat_id, content, reply_to=None, metadata=None):
            return await super().send(chat_id, content, reply_to, metadata)

    Sub.__abstractmethods__ = frozenset()  # only send/edit_message matter here
    a = Sub.__new__(Sub)
    asyncio.run(a.send("1", "run hermes setup tts"))
    asyncio.run(a.send(chat_id="1", content="Run `hermes doctor`"))
    asyncio.run(a.edit_message("1", "m", "hermes gateway restart"))
    assert sent == ["run nokker setup tts", "Run `nokker doctor`", "nokker gateway restart"]
    assert inspect.iscoroutinefunction(Sub.send) and Sub.send._nokker_brand


# ── prompt ───────────────────────────────────────────────────────────────────────────────────

_IMPORT_TIME_PROBE = r"""
import contextlib, io, json
from agent import prompt_builder as pb
from hermes_cli._parser import build_top_level_parser
from hermes_cli import banner, skin_engine
parser = build_top_level_parser()[0]
buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
    parser.parse_args(["--help"])
print(json.dumps({
    "identity": pb.DEFAULT_AGENT_IDENTITY, "help": pb.HERMES_AGENT_HELP_GUIDANCE,
    "help_no_skills": pb.HERMES_AGENT_HELP_GUIDANCE_NO_SKILLS, "prog": parser.prog, "help_out": buf.getvalue(),
    "logo": banner.HERMES_AGENT_LOGO, "agent_name": skin_engine.load_skin("default").get_branding("agent_name"),
    "mono_name": skin_engine.load_skin("mono").get_branding("agent_name"),
    "version_wrapped": hasattr(banner.format_banner_version_label, "__wrapped__"),
}))
"""


@pytest.fixture(scope="module")
def import_time(tmp_path_factory):
    return _branded_subprocess(_IMPORT_TIME_PROBE, tmp_path_factory.mktemp("home"))


def test_prompt_constants(import_time):
    assert import_time["identity"].startswith("You are Nokker. Be direct")
    for text in (import_time["help"], import_time["help_no_skills"]):
        assert "Nous Research" not in text and "Hermes" not in text and nb.DOCS_URL in text
    assert "skill_view(name='hermes-agent')" in import_time["help"]  # the skill id is code


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def test_top_level_parser_is_nokker(import_time):
    assert import_time["prog"] == "nokker"
    out = import_time["help_out"]
    assert out.startswith("usage: nokker") and "Hermes Agent" not in out and "Nokker - AI assistant" in out


def test_legacy_prog():
    assert nb.legacy_prog("nokker") == "hermes"
    assert nb.legacy_prog("nokker auth") == "hermes auth"
    assert nb.legacy_prog("/kanban") == "/kanban"


def test_color_helper_rebrands(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    from hermes_cli.colors import color
    assert color("Retry with: hermes setup tts") == "Retry with: nokker setup tts"


def test_banner_and_skin(import_time):
    assert "███╗   ██╗ ██████╗ ██╗  ██╗" in import_time["logo"]
    assert import_time["agent_name"] == "Nokker" and import_time["mono_name"] == "Nokker"
    assert import_time["version_wrapped"]


def test_i18n_catalog_rebranded(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from agent import i18n
    i18n._catalog_cache.clear()
    cat = i18n._load_catalog("en", str(tmp_path))
    leaked = {k: v for k, v in cat.items() if isinstance(v, str) and nb.rebrand_text(v, prose=True) != v}
    assert not leaked
    assert not any("hermes setup" in v for v in cat.values() if isinstance(v, str))


# ── environment ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env, want", [
    ({"NOKKER_HOME": "/srv/n"}, "/srv/n"),
    ({"NOKKER_HOME": "/srv/n", "HERMES_HOME": "/opt/data"}, "/opt/data"),  # the image's baked value wins
    ({"HERMES_HOME": "/opt/data"}, "/opt/data"),
])
def test_home_alias(env, want, tmp_path):
    import os
    import subprocess
    import sys
    base = {k: v for k, v in os.environ.items() if k not in ("HERMES_HOME", "NOKKER_HOME")}
    code = "import os, hermes_constants; print(os.environ['HERMES_HOME']); print(os.environ.get('NOKKER_HOME', '-'))"
    out = subprocess.run([sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True,
                         cwd=os.path.dirname(nb.__file__), check=True).stdout.split()
    assert out[0] == want
    assert out[1] == env.get("NOKKER_HOME", "-")  # NOKKER_HOME is never written
