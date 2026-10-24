from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "migration"
    / "openclaw-migration"
    / "scripts"
    / "openclaw_to_hermes.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("openclaw_to_hermes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_skills_guard():
    spec = importlib.util.spec_from_file_location(
        "skills_guard_local",
        Path(__file__).resolve().parents[2] / "tools" / "skills_guard.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_markdown_entries_promotes_heading_context():
    mod = load_module()
    text = """# MEMORY.md - Long-Term Memory

## Tyler Williams

- Founder of VANTA Research
- Timezone: America/Los_Angeles

### Active Projects

- Hermes Agent
"""
    entries = mod.extract_markdown_entries(text)
    assert "Tyler Williams: Founder of VANTA Research" in entries
    assert "Tyler Williams: Timezone: America/Los_Angeles" in entries
    assert "Tyler Williams > Active Projects: Hermes Agent" in entries


def test_extract_markdown_entries_merges_soft_wrapped_bullet_continuation():
    """Regression: a bullet hand-wrapped across physical lines (no blank line,
    no new "- ") used to become TWO entries -- the bullet's first line, cut
    mid-sentence, then the continuation re-prefixed with the same section
    heading as if it were a brand-new, unrelated paragraph. Both bloated the
    character count merge_entries() checks against (the heading repeated
    twice) and truncated the actual content."""
    mod = load_module()
    text = """# MEMORY.md

## Humans

- Les humains du foyer et mes co-fondateurs: Bruno, Partenaire d'Alice sur
  la totalite des projets (perso et pro).
- Second bullet, single line.
"""
    entries = mod.extract_markdown_entries(text)
    assert len(entries) == 2
    assert entries[0] == (
        "Humans: Les humains du foyer et mes co-fondateurs: Bruno, Partenaire "
        "d'Alice sur la totalite des projets (perso et pro)."
    )
    assert entries[1] == "Humans: Second bullet, single line."
    # The heading must appear exactly once per entry, not once per physical line.
    assert entries[0].count("Humans:") == 1


def test_extract_markdown_entries_merges_soft_wrapped_paragraph_continuation():
    mod = load_module()
    text = """# USER.md

## Bio

Alice works at Acme and is building several products at once, including
ninjob and SOKKAN, across a small team.

Second paragraph here.
"""
    entries = mod.extract_markdown_entries(text)
    assert entries == [
        "Bio: Alice works at Acme and is building several products at once, "
        "including ninjob and SOKKAN, across a small team.",
        "Bio: Second paragraph here.",
    ]


def test_extract_markdown_entries_new_bullet_ends_previous_bullet_continuation():
    """Two bullets back-to-back, each wrapped across two physical lines, with
    no blank line anywhere -- every physical line must land in the right
    entry, not bleed into its neighbour."""
    mod = load_module()
    text = """- First bullet starts here
  and continues here.
- Second bullet starts here
  and continues here too.
"""
    entries = mod.extract_markdown_entries(text)
    assert entries == [
        "First bullet starts here and continues here.",
        "Second bullet starts here and continues here too.",
    ]


def test_merge_entries_respects_limit_and_reports_overflow():
    mod = load_module()
    existing = ["alpha"]
    incoming = ["beta", "gamma is too long"]
    merged, stats, overflowed = mod.merge_entries(existing, incoming, limit=12)
    assert merged == ["alpha", "beta"]
    assert stats["added"] == 1
    assert stats["overflowed"] == 1
    assert overflowed == ["gamma is too long"]










def test_migrator_copies_skill_and_merges_allowlist(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()

    (source / "workspace" / "skills" / "demo-skill").mkdir(parents=True)
    (source / "workspace" / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: demo\n---\n\nbody\n",
        encoding="utf-8",
    )
    (source / "exec-approvals.json").write_text(
        json.dumps(
            {
                "agents": {
                    "*": {
                        "allowlist": [
                            {"pattern": "/usr/bin/*"},
                            {"pattern": "/home/test/**"},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (target / "config.yaml").write_text("command_allowlist:\n  - /usr/bin/*\n", encoding="utf-8")

    migrator = mod.Migrator(
        source_root=source,
        target_root=target,
        execute=True,
        workspace_target=None,
        overwrite=False,
        migrate_secrets=False,
        output_dir=target / "migration-report",
    )
    report = migrator.migrate()

    imported_skill = target / "skills" / mod.SKILL_CATEGORY_DIRNAME / "demo-skill" / "SKILL.md"
    assert imported_skill.exists()
    assert "/home/test/**" in (target / "config.yaml").read_text(encoding="utf-8")
    assert report["summary"]["migrated"] >= 2
    # The merge is written atomically — no temp file survives the run.
    assert [p.name for p in target.glob(".tmp*")] == []


def _allowlist_migrator(mod, tmp_path: Path, existing_config: str):
    """Migrator wired to merge an exec-approvals allowlist into config.yaml."""
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir(parents=True)
    (source / "exec-approvals.json").write_text(
        json.dumps({"agents": {"*": {"allowlist": [{"pattern": "/home/test/**"}]}}}),
        encoding="utf-8",
    )
    (target / "config.yaml").write_text(existing_config, encoding="utf-8")
    return mod.Migrator(
        source_root=source,
        target_root=target,
        execute=True,
        workspace_target=None,
        overwrite=False,
        migrate_secrets=False,
        output_dir=target / "migration-report",
    ), target / "config.yaml"


MALFORMED_HERMES_CONFIG = """\
model: hermes-4-405b
api_key_env: OPENROUTER_API_KEY
command_allowlist:
  - /usr/bin/*
approvals:
  deny: [shutdown *
telegram:
  enabled: true
"""


def test_unreadable_config_is_refused_not_overwritten(tmp_path: Path):
    """A present-but-unparseable config.yaml must survive the migration.

    ``load_yaml_file`` returned ``{}`` for an absent file AND for one it could
    not parse; the config-mutating steps read, merge and write the whole
    mapping back, so a YAML syntax error meant every existing setting was
    replaced by just the merged section.  Same defect as the ported twin in
    ``hermes_cli/agent_import.py``.
    """
    mod = load_module()
    migrator, config_path = _allowlist_migrator(
        mod, tmp_path, MALFORMED_HERMES_CONFIG)
    before = config_path.read_bytes()

    report = migrator.migrate()

    assert config_path.read_bytes() == before
    allowlist = [i for i in report["items"] if i["kind"] == "command-allowlist"]
    assert allowlist and allowlist[0]["status"] == mod.STATUS_ERROR
    assert "not valid YAML" in allowlist[0]["reason"]


def test_unreadable_config_blocks_later_config_steps_instead_of_partial_writes(
        tmp_path: Path):
    """One refusal flips the existing _config_apply_blocked short-circuit."""
    mod = load_module()
    migrator, config_path = _allowlist_migrator(
        mod, tmp_path, MALFORMED_HERMES_CONFIG)

    report = migrator.migrate()

    assert migrator._config_apply_blocked is True
    statuses = {
        i["status"] for i in report["items"]
        if i["kind"] in mod.Migrator._CONFIG_MUTATING_OPTIONS
    }
    # Nothing claimed a successful config write.
    assert "migrated" not in statuses
    assert config_path.read_text(encoding="utf-8") == MALFORMED_HERMES_CONFIG


def test_readable_config_keeps_every_pre_existing_key(tmp_path: Path):
    mod = load_module()
    migrator, config_path = _allowlist_migrator(
        mod,
        tmp_path,
        "model: hermes-4-405b\n"
        "api_key_env: OPENROUTER_API_KEY\n"
        "command_allowlist:\n  - /usr/bin/*\n",
    )

    migrator.migrate()

    import hermes_yaml as yaml

    merged = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert merged["model"] == "hermes-4-405b"
    assert merged["api_key_env"] == "OPENROUTER_API_KEY"
    assert "/usr/bin/*" in merged["command_allowlist"]
    assert "/home/test/**" in merged["command_allowlist"]


def test_absent_config_is_still_created(tmp_path: Path):
    """The guard must not break first-time creation.

    Only ``absent`` may read as ``{}``; ``model-config`` creates config.yaml
    from scratch when the target has none.
    """
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"model": "anthropic/claude-sonnet-4"}}}),
        encoding="utf-8",
    )
    config_path = target / "config.yaml"
    assert not config_path.exists()

    mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=True, migrate_secrets=False,
        output_dir=None, selected_options={"model-config"},
    ).migrate()

    assert "anthropic/claude-sonnet-4" in config_path.read_text(encoding="utf-8")


def test_symlinked_config_stays_a_symlink(tmp_path: Path):
    """Managed deployments symlink ~/.hermes/config.yaml into a dotfiles repo.

    A plain ``os.replace`` onto the link would detach it into a regular file;
    ``dump_yaml_file`` resolves the link first, as ``utils.atomic_replace`` does.
    """
    mod = load_module()
    real = tmp_path / "dotfiles" / "config.yaml"
    real.parent.mkdir(parents=True)
    real.write_text("model: hermes-4-405b\ncommand_allowlist:\n  - /usr/bin/*\n",
                    encoding="utf-8")
    migrator, config_path = _allowlist_migrator(mod, tmp_path, "placeholder: true\n")
    config_path.unlink()
    config_path.symlink_to(real)

    migrator.migrate()

    assert config_path.is_symlink()
    assert config_path.resolve() == real.resolve()
    assert "/home/test/**" in real.read_text(encoding="utf-8")
    assert "hermes-4-405b" in real.read_text(encoding="utf-8")


def test_unreadable_config_refused_by_model_config_too(tmp_path: Path):
    """The refusal is at the shared helper, so every config step inherits it."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"model": "anthropic/claude-sonnet-4"}}}),
        encoding="utf-8",
    )
    config_path = target / "config.yaml"
    config_path.write_text(MALFORMED_HERMES_CONFIG, encoding="utf-8")

    report = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=True, migrate_secrets=False,
        output_dir=None, selected_options={"model-config"},
    ).migrate()

    assert config_path.read_text(encoding="utf-8") == MALFORMED_HERMES_CONFIG
    items = [i for i in report["items"] if i["kind"] == "model-config"]
    assert items and items[0]["status"] == mod.STATUS_ERROR


def test_migrator_optionally_imports_supported_secrets_and_messaging_settings(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"

    (source / "credentials").mkdir(parents=True)
    (source / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": "/tmp/openclaw-workspace"}},
                "channels": {"telegram": {"botToken": "123:abc"}},
            }
        ),
        encoding="utf-8",
    )
    (source / "credentials" / "telegram-default-allowFrom.json").write_text(
        json.dumps({"allowFrom": ["111", "222"]}),
        encoding="utf-8",
    )
    target.mkdir()

    migrator = mod.Migrator(
        source_root=source,
        target_root=target,
        execute=True,
        workspace_target=None,
        overwrite=False,
        migrate_secrets=True,
        output_dir=target / "migration-report",
    )
    migrator.migrate()

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "MESSAGING_CWD=/tmp/openclaw-workspace" in env_text
    assert "TELEGRAM_ALLOWED_USERS=111,222" in env_text
    assert "TELEGRAM_BOT_TOKEN=123:abc" in env_text








def test_source_candidate_finds_files_in_custom_workspace(tmp_path: Path):
    """When agents.defaults.workspace points outside ~/.openclaw, files should
    be discovered there as a fallback."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    custom_ws = tmp_path / "my-custom-workspace"

    target.mkdir()
    source.mkdir()
    custom_ws.mkdir()

    # No workspace/ directory inside .openclaw — files live in custom workspace
    (custom_ws / "MEMORY.md").write_text("# Memory\n\n- custom workspace entry\n", encoding="utf-8")
    (custom_ws / "SOUL.md").write_text("# Soul\n\nI am me.\n", encoding="utf-8")
    (custom_ws / "skills" / "my-skill").mkdir(parents=True)
    (custom_ws / "skills" / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: test\n---\n\nbody\n",
        encoding="utf-8",
    )
    (custom_ws / "memory").mkdir()
    (custom_ws / "memory" / "2026-01-01.md").write_text("- daily note\n", encoding="utf-8")

    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(custom_ws)}}}),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source,
        target_root=target,
        execute=True,
        workspace_target=None,
        overwrite=False,
        migrate_secrets=False,
        output_dir=target / "migration-report",
        selected_options={"soul", "memory", "skills", "daily-memory"},
    )
    report = migrator.migrate()

    # SOUL.md should have been found and migrated
    assert (target / "SOUL.md").exists()

    # MEMORY.md should have been found and migrated
    assert (target / "memories" / "MEMORY.md").exists()
    mem_content = (target / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "custom workspace entry" in mem_content

    # Skills should have been found and migrated
    imported_skill = target / "skills" / mod.SKILL_CATEGORY_DIRNAME / "my-skill" / "SKILL.md"
    assert imported_skill.exists()

    migrated_kinds = {item["kind"] for item in report["items"] if item["status"] == "migrated"}
    assert "soul" in migrated_kinds
    assert "memory" in migrated_kinds
    assert "skill" in migrated_kinds












def test_slack_settings_migrated(tmp_path: Path):
    """Slack bot/app tokens and allowlist migrate to .env when secrets are enabled."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({
            "channels": {
                "slack": {
                    "botToken": "xoxb-slack-bot",
                    "appToken": "xapp-slack-app",
                    "allowFrom": ["U111", "U222"],
                }
            }
        }),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=True, output_dir=None,
        selected_options={"slack-settings"},
    )
    migrator.migrate()
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "SLACK_BOT_TOKEN=xoxb-slack-bot" in env_text
    assert "SLACK_APP_TOKEN=xapp-slack-app" in env_text
    assert "SLACK_ALLOWED_USERS=U111,U222" in env_text


def test_slack_tokens_require_migrate_secrets_flag(tmp_path: Path):
    """Regression: SLACK_BOT_TOKEN/SLACK_APP_TOKEN used to be written to .env
    unconditionally -- "slack-settings" never checked --migrate-secrets, unlike
    Telegram's botToken (secret-settings) and every other credential. A preset
    documented as excluding secrets (e.g. "user-data") still leaked them.
    The non-secret allowlist must still migrate, and the skip must be explicit
    (not merged silently into "No Slack settings found")."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({
            "channels": {
                "slack": {
                    "botToken": "xoxb-slack-bot",
                    "appToken": "xapp-slack-app",
                    "allowFrom": ["U111", "U222"],
                }
            }
        }),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"slack-settings"},
    )
    report = migrator.migrate()

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "xoxb-slack-bot" not in env_text
    assert "xapp-slack-app" not in env_text
    assert "SLACK_ALLOWED_USERS=U111,U222" in env_text  # non-secret, still migrates

    skip_items = [
        i for i in report["items"]
        if i["kind"] == "slack-settings" and i["status"] == "skipped"
        and "SLACK_BOT_TOKEN" in i["reason"]
    ]
    assert len(skip_items) == 1
    assert "SLACK_APP_TOKEN" in skip_items[0]["reason"]
    assert "--migrate-secrets" in skip_items[0]["reason"]
    assert mod.is_lossy_item(skip_items[0]) is True


def test_discord_token_requires_migrate_secrets_flag(tmp_path: Path):
    """Same regression and fix as Slack, for Discord's token."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({"channels": {"discord": {"token": "discord-real-token", "allowFrom": ["1"]}}}),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"discord-settings"},
    )
    report = migrator.migrate()

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "discord-real-token" not in env_text
    assert "DISCORD_ALLOWED_USERS=1" in env_text

    skip_items = [
        i for i in report["items"]
        if i["kind"] == "discord-settings" and i["status"] == "skipped"
        and "token" in i["reason"].lower()
    ]
    assert len(skip_items) == 1
    assert "--migrate-secrets" in skip_items[0]["reason"]

    # With secrets enabled, the token migrates too.
    migrator2 = mod.Migrator(
        source_root=source, target_root=target.parent / "hermes2", execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=True, output_dir=None,
        selected_options={"discord-settings"},
    )
    migrator2.migrate()
    env_text2 = (target.parent / "hermes2" / ".env").read_text(encoding="utf-8")
    assert "DISCORD_BOT_TOKEN=discord-real-token" in env_text2




def test_model_config_migrated(tmp_path: Path):
    """Default model setting migrates to config.yaml."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({
            "agents": {"defaults": {"model": "anthropic/claude-sonnet-4"}}
        }),
        encoding="utf-8",
    )
    # config.yaml must exist for YAML merge to work
    (target / "config.yaml").write_text("model: openrouter/auto\n", encoding="utf-8")

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=True, migrate_secrets=False, output_dir=None,
        selected_options={"model-config"},
    )
    migrator.migrate()
    config_text = (target / "config.yaml").read_text(encoding="utf-8")
    assert "anthropic/claude-sonnet-4" in config_text






def test_shared_skills_migrated(tmp_path: Path):
    """Shared skills from ~/.openclaw/skills/ are migrated."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()

    # Create a shared skill (not in workspace/skills/)
    (source / "skills" / "my-shared-skill").mkdir(parents=True)
    (source / "skills" / "my-shared-skill" / "SKILL.md").write_text(
        "---\nname: my-shared-skill\ndescription: shared\n---\n\nbody\n",
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"shared-skills"},
    )
    migrator.migrate()
    imported = target / "skills" / mod.SKILL_CATEGORY_DIRNAME / "my-shared-skill" / "SKILL.md"
    assert imported.exists()


def test_daily_memory_merged(tmp_path: Path):
    """Daily memory notes from workspace/memory/*.md are merged into MEMORY.md."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()

    mem_dir = source / "workspace" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "2026-03-01.md").write_text(
        "# March 1 Notes\n\n- User prefers dark mode\n- Timezone: PST\n",
        encoding="utf-8",
    )
    (mem_dir / "2026-03-02.md").write_text(
        "# March 2 Notes\n\n- Working on migration project\n",
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"daily-memory"},
    )
    migrator.migrate()
    mem_path = target / "memories" / "MEMORY.md"
    assert mem_path.exists()
    content = mem_path.read_text(encoding="utf-8")
    assert "dark mode" in content
    assert "migration project" in content


def test_provider_keys_require_migrate_secrets_flag(tmp_path: Path):
    """Provider keys migration is double-gated: needs option + --migrate-secrets."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({
            "models": {
                "providers": {
                    "openrouter": {
                        "apiKey": "sk-or-test-key",
                        "baseUrl": "https://openrouter.ai/api/v1",
                    }
                }
            }
        }),
        encoding="utf-8",
    )

    # Without --migrate-secrets: should skip
    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"provider-keys"},
    )
    migrator.migrate()
    env_path = target / ".env"
    if env_path.exists():
        assert "sk-or-test-key" not in env_path.read_text(encoding="utf-8")

    # With --migrate-secrets: should import
    migrator2 = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=True, output_dir=None,
        selected_options={"provider-keys"},
    )
    migrator2.migrate()
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-test-key" in env_text






def test_skill_installs_cleanly_under_skills_guard():
    skills_guard = load_skills_guard()
    result = skills_guard.scan_skill(
        SCRIPT_PATH.parents[1],
        source="official/migration/openclaw-migration",
    )

    # The migration script's references to agent config files are legitimate:
    # it mentions AGENTS.md to migrate workspace instructions and points the
    # user at ~/.hermes/config.yaml in its post-migration summary — it never
    # writes to either. Under skills-guard-v2 (#92021) these score as
    # informational _ref findings (the old critical agent_config_mod /
    # hermes_config_mod findings no longer fire for bare mentions), so the
    # verdict is "safe" with no modification-intent findings at all.
    assert result.verdict == "safe", f"Unexpected verdict: {result.verdict}"
    KNOWN_FALSE_POSITIVES = {"agent_config_ref", "hermes_config_ref"}
    for f in result.findings:
        assert f.pattern_id in KNOWN_FALSE_POSITIVES, f"Unexpected finding: {f}"


# ── rebrand_text tests ────────────────────────────────────────


def test_rebrand_text_replaces_openclaw_variants():
    mod = load_module()
    # Mixed-case / capitalized matches → capital-H ``Hermes``.
    assert mod.rebrand_text("OpenClaw prefers Python 3.11") == "Hermes prefers Python 3.11"
    assert mod.rebrand_text("I told Open Claw to use dark mode") == "I told Hermes to use dark mode"
    assert mod.rebrand_text("Open-Claw config is great") == "Hermes config is great"
    assert mod.rebrand_text("OPENCLAW uses tools well") == "Hermes uses tools well"
    # All-lowercase matches → lowercase ``hermes``; this preserves the
    # real filesystem path ``~/.hermes`` (Hermes home) when rebranding
    # memory entries that reference ``~/.openclaw`` or ``openclaw`` prose.
    assert mod.rebrand_text("openclaw should always respond concisely") == "hermes should always respond concisely"














# ── non-UTF-8 tolerance (issue #8901) ───────────────────────────────────────


def _write_invalid_utf8_json(path: Path, prefix: bytes, valid_value: bytes, suffix: bytes) -> None:
    """Write a JSON-shaped file containing one invalid UTF-8 byte (0xB3) inside
    a string value, alongside a separate, validly-encoded value. Used to check
    that a single bad byte does not prevent the rest of the file's data from
    being read (relies on read_text(..., errors="replace"))."""
    path.write_bytes(prefix + b"\xb3" + valid_value + suffix)


def test_command_allowlist_handles_invalid_utf8_bytes(tmp_path: Path):
    """exec-approvals.json with a non-UTF-8 byte should not abort migration;
    valid patterns elsewhere in the same file must still be imported."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    source.mkdir()
    target.mkdir()

    _write_invalid_utf8_json(
        source / "exec-approvals.json",
        prefix=b'{"agents": {"*": {"allowlist": [{"pattern": "/bad',
        valid_value=b'"}, {"pattern": "/usr/bin/*"}]}}}',
        suffix=b"",
    )
    (target / "config.yaml").write_text("command_allowlist: []\n", encoding="utf-8")

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"command-allowlist"},
    )
    report = migrator.migrate()

    items = [i for i in report["items"] if i["kind"] == "command-allowlist"]
    assert items and items[0]["status"] == "migrated"
    config_text = (target / "config.yaml").read_text(encoding="utf-8")
    assert "/usr/bin/*" in config_text


def test_messaging_settings_handles_invalid_utf8_in_telegram_allowlist(tmp_path: Path):
    """Telegram allowFrom file with a non-UTF-8 byte should not abort migration;
    valid user IDs elsewhere in the same file must still be imported."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    source.mkdir()
    target.mkdir()

    creds_dir = source / "credentials"
    creds_dir.mkdir()
    _write_invalid_utf8_json(
        creds_dir / "telegram-default-allowFrom.json",
        prefix=b'{"allowFrom": ["bad',
        valid_value=b'", "123456789"]}',
        suffix=b"",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"messaging-settings"},
    )
    report = migrator.migrate()

    items = [i for i in report["items"] if i["kind"] == "messaging-settings"]
    assert items and items[0]["status"] == "migrated"
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "123456789" in env_text


# ---------------------------------------------------------------------------
# reconcile_unaccounted_source_paths / is_lossy_item
#
# Regression tests for NousResearch/hermes-agent#5191 and #7847 ("hermes claw
# migrate: silent failures"): a file under the OpenClaw source tree that no
# migrate_* step or archive_docs() allowlist knows about used to vanish from
# the report with zero trace. These tests pin the fix: such a file is now
# always surfaced as an "unsupported" item, and that item (like any other
# real, un-acknowledged data loss) is flagged by is_lossy_item().
# ---------------------------------------------------------------------------


def test_unaccounted_source_path_is_reported_not_silent(tmp_path: Path):
    """A directory no migration step has ever heard of must show up in the
    report as 'unsupported', not disappear."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    # A plausible future/unknown OpenClaw subsystem with no migration rule.
    flows_dir = source / "flows"
    flows_dir.mkdir()
    (flows_dir / "registry.sqlite").write_bytes(b"not-a-real-sqlite-file")

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        # A narrow, non-empty selection: Migrator treats an *empty* set the
        # same as "all" (``selected_options or MIGRATION_OPTION_METADATA.keys()``),
        # so to get real "Not selected for this run" skips we must pick one
        # option and leave the rest out.
        selected_options={"soul"},
    )
    report = migrator.migrate()

    unaccounted = [i for i in report["items"] if i["kind"] == "unaccounted-source"]
    assert len(unaccounted) == 1
    item = unaccounted[0]
    assert item["status"] == "unsupported"
    assert item["source"] == str(flows_dir)
    assert "registry.sqlite" in item["reason"]
    assert report["summary"]["unsupported"] == 1

    # It is real, un-acknowledged data loss, unlike the dozens of
    # "Not selected for this run" items from the empty selection above.
    assert mod.is_lossy_item(item) is True
    not_selected = [i for i in report["items"] if i.get("reason") == "Not selected for this run"]
    assert not_selected  # sanity: the empty-selection run does produce these
    assert all(mod.is_lossy_item(i) is False for i in not_selected)
    assert report["lossy_item_count"] == 1


def test_reconcile_does_not_flag_files_already_recorded(tmp_path: Path):
    """A file a migrate_* step actually looked at (SOUL.md) must not also be
    reported as unaccounted."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    workspace = source / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "SOUL.md").write_text("# Soul\n\nI am me.\n", encoding="utf-8")

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"soul"},
    )
    report = migrator.migrate()

    assert (target / "SOUL.md").exists()
    unaccounted = [i for i in report["items"] if i["kind"] == "unaccounted-source"]
    assert unaccounted == []
    assert report["summary"]["unsupported"] == 0


def test_is_lossy_item_treats_benign_skips_as_not_lossy():
    mod = load_module()
    assert mod.is_lossy_item(
        {"status": "skipped", "reason": "Not selected for this run", "source": None}
    ) is False
    assert mod.is_lossy_item(
        {"status": "skipped", "reason": "Target already matches source", "source": "/x"}
    ) is False
    assert mod.is_lossy_item(
        {"status": "skipped", "reason": "No OpenClaw SOUL.md found", "source": None}
    ) is False
    # Real data, examined, left behind -> lossy.
    assert mod.is_lossy_item(
        {"status": "skipped", "reason": "Contains secrets", "source": "/x/credentials"}
    ) is True
    assert mod.is_lossy_item({"status": "conflict", "source": "/x", "reason": "exists"}) is True
    assert mod.is_lossy_item({"status": "error", "source": None, "reason": "boom"}) is True
    assert mod.is_lossy_item({"status": "unsupported", "source": "/x", "reason": "n/a"}) is True
    assert mod.is_lossy_item({"status": "migrated", "source": "/x", "reason": ""}) is False
    assert mod.is_lossy_item({"status": "archived", "source": "/x", "reason": ""}) is False


# ---------------------------------------------------------------------------
# Gateway auth/password schema drift (found auditing a real OpenClaw config:
# ``gateway.auth`` uses {mode, password}, not the {token} shape the original
# code only ever checked — so a real gateway password was archived raw but
# never imported, and never even recorded as skipped).
# ---------------------------------------------------------------------------


def test_gateway_password_migrated_with_migrate_secrets(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({
            "gateway": {
                "auth": {"mode": "password", "password": "s3cr3t-gateway-pw"},
                "remote": {"password": "s3cr3t-remote-pw"},
            }
        }),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=True, output_dir=None,
        selected_options={"gateway-config"},
    )
    report = migrator.migrate()

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "HERMES_GATEWAY_PASSWORD=s3cr3t-gateway-pw" in env_text
    assert "HERMES_GATEWAY_REMOTE_PASSWORD=s3cr3t-remote-pw" in env_text
    # _set_env_var() records these under kind "env-var" (not "gateway-config").
    env_items = [i for i in report["items"] if i["kind"] == "env-var"]
    migrated_destinations = {i["destination"] for i in env_items if i["status"] == "migrated"}
    assert ".env HERMES_GATEWAY_PASSWORD" in migrated_destinations
    assert ".env HERMES_GATEWAY_REMOTE_PASSWORD" in migrated_destinations


def test_gateway_password_skipped_with_reason_without_migrate_secrets(tmp_path: Path):
    """Without --migrate-secrets, the password must be explicitly flagged as
    skipped -- not silently absent from both .env and the report."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()

    (source / "openclaw.json").write_text(
        json.dumps({"gateway": {"auth": {"mode": "password", "password": "s3cr3t-gateway-pw"}}}),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"gateway-config"},
    )
    report = migrator.migrate()

    env_path = target / ".env"
    if env_path.exists():
        assert "s3cr3t-gateway-pw" not in env_path.read_text(encoding="utf-8")

    gw_password_items = [
        i for i in report["items"]
        if i["kind"] == "gateway-config" and i.get("source") == "openclaw.json gateway.auth.password"
    ]
    assert len(gw_password_items) == 1
    assert gw_password_items[0]["status"] == "skipped"
    assert mod.is_lossy_item(gw_password_items[0]) is True


# ---------------------------------------------------------------------------
# archive_docs() crash on a custom (outside source_root) workspace.
#
# Found running the real, patched engine end-to-end against a sanitized copy
# of a production OpenClaw install whose agents.defaults.workspace points
# outside ~/.openclaw/ (our own install's actual shape). Under --preset full
# (the CLI default), archive_docs() tries to archive IDENTITY.md/TOOLS.md/etc
# found via the custom-workspace fallback in source_candidate(), and crashed
# with shutil.SameFileError: relative_label() returns an ABSOLUTE path for
# anything outside source_root, and `archive_dir / "<absolute path>"` silently
# discards archive_dir (pathlib join semantics), making the computed
# destination equal to the source file itself.
# ---------------------------------------------------------------------------


def test_archive_docs_does_not_crash_on_custom_workspace(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    custom_ws = tmp_path / "my-custom-workspace"
    target.mkdir()
    source.mkdir()
    custom_ws.mkdir()

    (custom_ws / "IDENTITY.md").write_text("# Identity\n\nI am Nina.\n", encoding="utf-8")
    (custom_ws / "TOOLS.md").write_text("# Tools\n", encoding="utf-8")
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(custom_ws)}}}),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False,
        output_dir=target / "migration-report",
        selected_options={"archive"},
    )
    # Must not raise shutil.SameFileError.
    report = migrator.migrate()

    archived = [i for i in report["items"] if i["kind"] == "archive" and i["status"] == "archived"]
    archived_sources = {i["source"] for i in archived}
    assert str(custom_ws / "IDENTITY.md") in archived_sources
    assert str(custom_ws / "TOOLS.md") in archived_sources
    for item in archived:
        dest = Path(item["destination"])
        assert dest.exists()
        assert dest != Path(item["source"])
        assert dest.read_text(encoding="utf-8") == Path(item["source"]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# auth-profiles.json: unmapped provider names (found auditing a real install
# whose only two profiles are "xai:default" and "infomaniak:default" -- the
# original code matched only openrouter/openai/anthropic by substring, so
# these two keys were read and then dropped with zero trace anywhere in the
# report, and the file itself never appeared as any item's source either
# (so reconcile_unaccounted_source_paths() would have called it "unsupported"
# -- misleading, since it genuinely was parsed).
# ---------------------------------------------------------------------------


def test_auth_profiles_unmapped_provider_is_reported_not_silent(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    agent_dir = source / "agents" / "main" / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "auth-profiles.json").write_text(
        json.dumps({
            "profiles": {
                "xai:default": {"key": "xai-real-key"},
                "infomaniak:default": {"key": "infomaniak-real-key"},
                "openrouter:default": {"key": "or-real-key"},
            }
        }),
        encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=True, output_dir=None,
        selected_options={"provider-keys"},
    )
    report = migrator.migrate()

    # The known provider (openrouter) still migrates normally.
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=or-real-key" in env_text
    assert "xai-real-key" not in env_text
    assert "infomaniak-real-key" not in env_text

    auth_profiles_path = agent_dir / "auth-profiles.json"

    # The file itself is marked examined (not a loss by itself)...
    file_level = [i for i in report["items"]
                  if i["kind"] == "provider-keys" and i["source"] == str(auth_profiles_path)]
    assert file_level and file_level[0]["status"] == "migrated"

    # ...while each unmapped profile is its own explicit, lossy item.
    xai_items = [i for i in report["items"]
                 if i["kind"] == "provider-keys" and i.get("source") == f"{auth_profiles_path} :: xai:default"]
    assert len(xai_items) == 1
    assert xai_items[0]["status"] == "skipped"
    assert "xai:default" in xai_items[0]["reason"]
    assert mod.is_lossy_item(xai_items[0]) is True

    infomaniak_items = [
        i for i in report["items"]
        if i["kind"] == "provider-keys" and i.get("source") == f"{auth_profiles_path} :: infomaniak:default"
    ]
    assert len(infomaniak_items) == 1
    assert infomaniak_items[0]["status"] == "skipped"
    assert mod.is_lossy_item(infomaniak_items[0]) is True

    # reconcile_unaccounted_source_paths() must not ALSO flag the file as
    # "unsupported" now that it is covered by the file-level item above.
    unaccounted = [i for i in report["items"]
                   if i["kind"] == "unaccounted-source" and str(auth_profiles_path) in (i["source"] or "")]
    assert unaccounted == []


# ---------------------------------------------------------------------------
# resolve_selected_options(): --preset + --include combined.
#
# Regression found running `--preset user-data --include soul,user-profile,
# memory,daily-memory,skills,shared-skills,ui-identity` against a real
# OpenClaw config: messaging-settings and slack-settings (both part of the
# "user-data" preset, neither in --include) still ran and wrote
# SLACK_BOT_TOKEN/SLACK_APP_TOKEN to .env. --include was silently discarded
# whenever --preset was also given.
# ---------------------------------------------------------------------------


def test_resolve_selected_options_include_narrows_a_preset():
    mod = load_module()
    selected = mod.resolve_selected_options(
        include=["soul,user-profile,memory,daily-memory,skills,shared-skills,ui-identity"],
        exclude=None,
        preset="user-data",
    )
    assert selected == {
        "soul", "user-profile", "memory", "daily-memory", "skills", "shared-skills", "ui-identity",
    }
    # Confirm the premise: all seven are indeed part of the preset (otherwise
    # this test would pass for the wrong reason -- an empty intersection
    # looks the same as a correct narrowing at a glance).
    assert selected <= mod.MIGRATION_PRESETS["user-data"]
    assert "messaging-settings" in mod.MIGRATION_PRESETS["user-data"]
    assert "slack-settings" in mod.MIGRATION_PRESETS["user-data"]


def test_resolve_selected_options_preset_alone_is_unaffected():
    """No --include at all: a bare --preset must still select the whole preset."""
    mod = load_module()
    selected = mod.resolve_selected_options(include=None, exclude=None, preset="user-data")
    assert selected == mod.MIGRATION_PRESETS["user-data"]


def test_resolve_selected_options_include_all_keyword_keeps_whole_preset():
    mod = load_module()
    selected = mod.resolve_selected_options(include=["all"], exclude=None, preset="user-data")
    assert selected == mod.MIGRATION_PRESETS["user-data"]


def test_resolve_selected_options_exclude_still_applies_after_narrowing():
    mod = load_module()
    selected = mod.resolve_selected_options(
        include=["soul,memory"], exclude=["memory"], preset="user-data",
    )
    assert selected == {"soul"}


def test_preset_user_data_with_narrow_include_does_not_touch_slack(tmp_path: Path):
    """End-to-end: the exact flag combination from the real-world repro must
    not migrate messaging-settings/slack-settings, and must not write any
    Slack token to .env."""
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()
    (source / "openclaw.json").write_text(
        json.dumps({
            "channels": {"slack": {"botToken": "xoxb-should-not-migrate", "appToken": "xapp-should-not-migrate"}},
        }),
        encoding="utf-8",
    )

    selected = mod.resolve_selected_options(
        include=["soul,user-profile,memory,daily-memory,skills,shared-skills,ui-identity"],
        exclude=None,
        preset="user-data",
    )
    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options=selected, preset_name="user-data",
    )
    report = migrator.migrate()

    env_path = target / ".env"
    if env_path.exists():
        env_text = env_path.read_text(encoding="utf-8")
        assert "xoxb-should-not-migrate" not in env_text
        assert "xapp-should-not-migrate" not in env_text

    ran_kinds = {i["kind"] for i in report["items"] if i.get("reason") != "Not selected for this run"}
    assert "messaging-settings" not in ran_kinds
    assert "slack-settings" not in ran_kinds
    not_selected = {i["kind"] for i in report["items"] if i.get("reason") == "Not selected for this run"}
    assert "messaging-settings" in not_selected
    assert "slack-settings" in not_selected


# ---------------------------------------------------------------------------
# migrate_shared_skills(): custom workspace fallback.
#
# The project-level skill paths were hardcoded as source_root/"workspace" and
# source_root/"workspace.default" -- unlike migrate_skills()'s
# source_candidate("workspace/skills"), they never checked a custom
# agents.defaults.workspace outside source_root (our own install's shape).
# ---------------------------------------------------------------------------


def test_shared_skills_found_in_custom_workspace(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    custom_ws = tmp_path / "my-custom-workspace"
    target.mkdir()
    source.mkdir()
    (custom_ws / ".agents" / "skills" / "proj-skill").mkdir(parents=True)
    (custom_ws / ".agents" / "skills" / "proj-skill" / "SKILL.md").write_text(
        "---\nname: proj-skill\ndescription: test\n---\n\nbody\n", encoding="utf-8",
    )
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(custom_ws)}}}), encoding="utf-8",
    )

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"shared-skills"},
    )
    report = migrator.migrate()

    imported = target / "skills" / mod.SKILL_CATEGORY_DIRNAME / "proj-skill" / "SKILL.md"
    assert imported.exists()
    # _import_skill_directory() records under "project-skills" for this
    # source (the option id "shared-skills" only labels run_if_selected()'s
    # own bookkeeping, e.g. the "Not selected for this run" skip).
    migrated = [i for i in report["items"] if i["kind"] == "project-skills" and i["status"] == "migrated"]
    assert migrated


# ---------------------------------------------------------------------------
# Memory/user-profile near-full warning.
#
# merge_entries() never lets the merged file exceed its character limit, but
# on a real install the migrated MEMORY.md/USER.md can legitimately land at
# or near 100% of the configured limit (repeated-heading bloat from the
# bullet-continuation bug above made this worse, but even after that fix a
# large legitimate memory file can fill the budget). That left the agent
# with ~0 characters of headroom to write anything new, with no signal
# anywhere that this had happened.
# ---------------------------------------------------------------------------


def test_memory_near_full_after_migration_is_warned_explicitly(tmp_path: Path):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    workspace = source / "workspace"
    workspace.mkdir(parents=True)

    limit = 200
    # Two bullets sized to land at >= 90% of a 200-char limit once merged.
    (workspace / "USER.md").write_text(
        "# USER.md\n\n"
        "- " + ("A" * 90) + "\n"
        "- " + ("B" * 90) + "\n",
        encoding="utf-8",
    )
    (target / "config.yaml").write_text(f"memory:\n  user_char_limit: {limit}\n", encoding="utf-8")

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"user-profile"},
    )
    report = migrator.migrate()

    user_item = next(i for i in report["items"] if i["kind"] == "user-profile")
    assert user_item["status"] == "migrated"
    assert user_item["details"]["final_char_count"] <= limit  # never exceeds
    assert user_item["details"]["final_char_count"] >= limit * mod.MEMORY_NEAR_FULL_RATIO

    near_full_warnings = [w for w in report["warnings"] if "little to no room" in w]
    assert len(near_full_warnings) == 1
    assert str(limit) in near_full_warnings[0]


# ---------------------------------------------------------------------------
# ruamel.yaml unavailable: clear message + no crash on the previously
# unguarded config.yaml writers (mcp-servers, full-providers, agent-config,
# gateway-config, ...). dump_yaml_file() used to raise a bare RuntimeError,
# which only the three callers that pre-checked `yaml is None` themselves
# (model-config, tts-config, command-allowlist) ever avoided -- every other
# config.yaml writer propagated the RuntimeError uncaught, crashing migrate()
# entirely instead of recording one clean "error" item.
# ---------------------------------------------------------------------------


def test_ruamel_unavailable_produces_clean_error_not_a_crash(tmp_path: Path, monkeypatch):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()
    # mcp-servers is one of the config.yaml writers that never pre-checked
    # `yaml is None` itself -- it relied entirely on dump_yaml_file() raising.
    (source / "openclaw.json").write_text(
        json.dumps({"mcp": {"servers": {"browser": {"url": "http://localhost:1/mcp"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "yaml", None)

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"mcp-servers"},
    )
    # Must not raise.
    report = migrator.migrate()

    error_items = [i for i in report["items"] if i["kind"] == "mcp-servers" and i["status"] == "error"]
    assert len(error_items) == 1
    assert "ruamel.yaml" in error_items[0]["reason"]
    assert "pip install" in error_items[0]["reason"]
    assert mod.is_lossy_item(error_items[0]) is True


def test_ruamel_unavailable_message_is_actionable_for_model_config(tmp_path: Path, monkeypatch):
    mod = load_module()
    source = tmp_path / ".openclaw"
    target = tmp_path / ".hermes"
    target.mkdir()
    source.mkdir()
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"model": "anthropic/claude-opus-4-6"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "yaml", None)

    migrator = mod.Migrator(
        source_root=source, target_root=target, execute=True,
        workspace_target=None, overwrite=False, migrate_secrets=False, output_dir=None,
        selected_options={"model-config"},
    )
    report = migrator.migrate()

    item = next(i for i in report["items"] if i["kind"] == "model-config")
    assert item["status"] == "error"
    assert "pip install" in item["reason"]
    assert "hermes claw migrate" in item["reason"]




