# `hermes claw migrate` — what was broken, what this patch does

This covers the OpenClaw → Hermes migration tool: the engine at
`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py`
and its CLI wrapper at `hermes_cli/claw.py` / `hermes_cli/subcommands/claw.py`
(`hermes claw migrate` / `hermes claw cleanup`).

## The bug class: silent failures

Upstream tracked this as two issues:

- [NousResearch/hermes-agent#5191](https://github.com/NousResearch/hermes-agent/issues/5191) —
  "hermes claw migrate: two silent failures break gateway after OpenClaw
  migration" (the canonical/interlocked thread).
- [NousResearch/hermes-agent#7847](https://github.com/NousResearch/hermes-agent/issues/7847) —
  a follow-up audit that filed five independent one-file PRs (#7860, #7861,
  #7862, #7864, #7868) plus a sixth (#7869) after a community audit of ~180
  Discord messages over two weeks found migration was consistently the
  single most common pain point.

None of those PRs were merged (all closed without landing), but by the time
this fork was taken (Hermes v0.22.2) the engine already carried equivalent
fixes for most of what they described: `workspace-main/` fallback, the
`edge`/`microsoft` TTS rename, `accounts.default` channel token paths,
`thinkingDefault` mapping, hyphenated `apiType` values, Matrix `accessToken`,
and SecretRef `file`/`exec` detection are all already in the code (see
`source_candidate()`, `migrate_tts_config()`, `_get_channel_field()`,
`migrate_agent_config()`, `migrate_full_providers()`, `migrate_deep_channels()`,
and the `raw_key.get("source") in {"file", "exec"}` check in
`migrate_provider_keys()`).

What was **not** fixed, because the bug is structural rather than a missing
field mapping: every `migrate_*` function and `archive_docs()`'s allowlist is
a hand-maintained list of OpenClaw paths and config keys. A file or directory
this script has never heard of — a new OpenClaw subsystem, a provider name
its name-matching heuristics don't recognize, a config shape it has never
seen — did not get a "skipped" entry. It got **nothing**: no line in
`summary.md`, no entry in `report.json`, exit code 0. The tool enumerates
what it knows; it never reconciles that against what is actually there. Every
PR filed against #7847 fixed one more hand-coded path, and the next OpenClaw
release added a new one the same way.

## What this patch does

### 1. Structural fix: `reconcile_unaccounted_source_paths()`

A new pass, run unconditionally at the end of `Migrator.migrate()` (even when
most options are deselected via `--preset`/`--include`/`--exclude`), walks
the OpenClaw source tree (and the resolved workspace, including a custom
`agents.defaults.workspace` outside `~/.openclaw/`) and compares every file
against the `source` of every item already recorded. Anything not the exact
source of a recorded item, and not inside a directory that is one, gets a
single grouped item per top-level path:

```
kind="unaccounted-source", status="unsupported",
reason="Not read by any migration step in this version of claw migrate. ..."
```

Nothing is read, copied, or deleted by this pass — it only makes existing
silence visible. The new `unsupported` status is added to the summary counts,
the warnings, and the `## What Was Not Fully Brought Over` section of
`summary.md`.

This is why item-level fixes still had value: a fix doesn't just satisfy the
new reconciliation pass, it (where possible) actually gets the data into
Hermes or files it with an accurate, specific reason instead of a generic
"not covered by this version."

### 2. `is_lossy_item()` + `--accept-skips`

A migration that reports `migrated: 12, skipped: 0, conflict: 0, error: 0`
can still have silently dropped real data under the old code — "skipped"
included both "there was genuinely nothing to migrate" and "there was data,
and it didn't make it." Those two cases are now distinguished:

- **Benign** (not lossy): the option was deliberately deselected
  (`reason == "Not selected for this run"`), or the destination already held
  byte-identical content (`reason == "Target already matches source"`), or
  the step looked and found nothing (`status == "skipped"` with `source is
  None`).
- **Lossy** (real data left behind): `status` is `conflict`, `error`, or
  `unsupported`; or `status == "skipped"` with a `source` set (something was
  found and not migrated).

`hermes claw migrate` (outside `--dry-run`) now exits non-zero when any lossy
item remains and `--accept-skips` was not passed — printing the count and
pointing at the saved report. This is the "never report success while
quietly leaving data behind" fix. `--dry-run` is unaffected: a preview never
needs acknowledgment, only an applied run does.

### 3. Concrete gaps found auditing a real install

Two schema-drift bugs and one crash, found by running the patched engine
end-to-end against a sanitized production OpenClaw config (the generic fixes
above made both "visible" instead of invisible; fixing them was the next
step):

- **`gateway.auth.password` / `gateway.remote.password` never inspected.**
  The original code only ever checked `gateway.auth.token` — an older,
  bearer-token OpenClaw gateway auth shape. A newer install using
  `auth.mode: "password"` with a plain `auth.password` (plus a separate
  `remote.password` for remote-gateway access) had neither value even
  looked at: not imported, not archived individually, not flagged as
  skipped. `migrate_gateway_config()` now resolves all three fields
  through the existing `resolve_secret_input()` and either imports them
  (`--migrate-secrets`) or records an explicit skip with the reason.

- **`auth-profiles.json` provider names outside openrouter/openai/anthropic.**
  The per-agent `auth-profiles.json` credential scan only recognized
  profile names containing `openrouter`, `openai`, or `anthropic`. Any other
  provider profile (e.g. a profile named `xai:default` or
  `infomaniak:default`) was read, key-checked, and then discarded with zero
  trace — and because no item ever recorded the file itself as a `source`,
  the new reconciliation pass would also have called it "unsupported",
  which is misleading for a file that genuinely was parsed. Each profile now
  gets its own item: matched ones still feed the known env var, unmapped
  ones are recorded as skipped with the profile name in the reason, and the
  file itself is recorded once (`status="migrated"`, informational) so
  reconciliation can tell "parsed, nothing matched" apart from "never
  opened."

- **`archive_path()` crash on a custom (external) workspace.** Running
  `--preset full` (the CLI default) against a config whose
  `agents.defaults.workspace` points outside `~/.openclaw/` — a supported,
  documented shape (see `source_candidate()`'s custom-workspace fallback,
  already present before this patch) — crashed with
  `shutil.SameFileError`. `archive_docs()` tries to archive files like
  `IDENTITY.md` found through that fallback; the helper computing the
  archive destination (`relative_label()`) falls back to the file's
  **absolute** path for anything outside `source_root`, and
  `archive_dir / "<absolute path>"` in `pathlib` silently *discards*
  `archive_dir` (`Path("/a") / "/b" == Path("/b")`) — so the computed
  destination was the source file itself. `archive_path()` now builds the
  destination through a dedicated `_safe_archive_subpath()` that never
  produces an absolute join, whether the source is inside `source_root`,
  inside the custom workspace, or any other path outside the source tree.

## New report shape

`report.json` gained two fields:

- `summary.unsupported` — count of `unaccounted-source` items from the
  reconciliation pass.
- `lossy_item_count` — count of items `is_lossy_item()` considers real,
  un-acknowledged data loss (see above).

`summary.md` gained a `## Needs Your Acknowledgment` section stating the
lossy count and the `--accept-skips` instruction, and its existing
`## What Was Not Fully Brought Over` section now also lists `unsupported`
items alongside `skipped`/`conflict`/`error`.

## Running it

```
hermes claw migrate --dry-run                  # preview, never exits non-zero
hermes claw migrate                             # applies; exits 2 if any lossy item remains
hermes claw migrate --accept-skips              # applies; exits 0 regardless, after you've reviewed the list
hermes claw migrate --migrate-secrets --accept-skips --overwrite   # typical "just get me unblocked" run
```

The printed report (and `<hermes_home>/migration/openclaw/<timestamp>/summary.md`)
now has a `⚠ Not covered by this migration version:` section alongside the
existing `Skipped:`/`Conflicts:`/`Errors:` ones — review that list before
passing `--accept-skips`, since it is exactly the set of files this version
of the tool has no opinion about at all.

## Tests

`tests/skills/test_openclaw_migration.py` has the new regression tests,
alongside the existing upstream suite for this engine:

- `test_unaccounted_source_path_is_reported_not_silent` /
  `test_reconcile_does_not_flag_files_already_recorded` — the reconciliation
  pass itself.
- `test_is_lossy_item_treats_benign_skips_as_not_lossy` — the
  benign-vs-lossy classification.
- `test_gateway_password_migrated_with_migrate_secrets` /
  `test_gateway_password_skipped_with_reason_without_migrate_secrets` — the
  `gateway.auth`/`remote` schema-drift fix.
- `test_auth_profiles_unmapped_provider_is_reported_not_silent` — the
  `auth-profiles.json` per-profile fix.
- `test_archive_docs_does_not_crash_on_custom_workspace` — the
  `archive_path()` crash fix.

Run just this engine's tests (not the full suite):

```
pytest tests/skills/test_openclaw_migration.py \
       tests/skills/test_openclaw_migration_hardening.py \
       tests/hermes_cli/test_claw.py \
       tests/hermes_cli/test_setup_openclaw_migration.py
```

## Round 2: four more gaps found running the patched tool for real

The fixes above shipped on `main`. Running the result as a canary against a
second sanitized copy of a real production OpenClaw config surfaced four
more issues — none were in the upstream issue threads; all four were found
by actually using the tool, which is exactly the point of keeping a canary.

### 1. Soft-wrapped bullets/paragraphs split into multiple, re-prefixed entries

`extract_markdown_entries()` ended a "paragraph" block on any line that
wasn't itself blank/heading/bullet/table — so a bullet or paragraph
hand-wrapped across physical lines (very common; MEMORY.md/USER.md are
hand-edited) had its first line become one entry and every continuation
line become its own **separate** entry, each re-prefixed with the same
section heading. On a real install this inflated `MEMORY.md` from 76
logical entries (after the fix) to 112 raw fragments, and `USER.md` from 22
to 30 — and truncated bullets mid-sentence in the process (an `overflow_preview`
value literally read `"...**Rôle réel:** co-fondatrice / partenaire d'Alice
**sur la totalité des"`, cut off exactly where the physical line wrapped).

Fixed by merging continuation lines into whichever block (paragraph or
bullet) is currently open, flushing only on a blank line, heading, new
bullet, table row, or code-fence toggle — never mid-block.

### 2. `limit`-character memory/user files landed 1 character over `limit`

`merge_entries()` strictly enforces that `len(ENTRY_DELIMITER.join(merged))`
never exceeds the configured limit — but `migrate_memory()` then writes
`ENTRY_DELIMITER.join(merged) + "\n"` to disk, a trailing newline
`merge_entries()` never knew about. A fully-packed file landed at exactly
`limit + 1` characters (observed: `USER.md` at 1376 chars against a
1375-character limit). `migrate_memory()` now reserves 1 character for that
newline before calling `merge_entries()`.

Separately, a migration can legitimately fill the budget to ~100% even
without that off-by-one — merge_entries() will happily add entries right up
to the limit, and nothing said so. `Migrator._build_warnings()` now adds an
explicit warning whenever migrated memory/user-profile content lands at
≥90% of its limit (`MEMORY_NEAR_FULL_RATIO`), and whenever any entries
overflowed into the `overflow/*.txt` file instead of merging — both used to
be visible only inside one item's `details`, easy to miss in a terminal
recap or a glance at `summary.md`.

### 3. `--preset` silently discarded `--include`

`resolve_selected_options()` took the preset branch unconditionally when
`--preset` was given, ignoring `--include` entirely. Running
`--preset user-data --include soul,memory,...` (a narrow, intentional
subset) still ran **every** option in the `user-data` preset — including
`messaging-settings` and `slack-settings`, which are part of that preset's
definition. `--include` now narrows (intersects) a preset instead of being
discarded by it; `--exclude` still applies afterward.

### 4. "Secret-excluding" preset wrote Slack/Discord bot tokens anyway

Independent of #3: `migrate_slack_settings()` and `migrate_discord_settings()`
never checked `self.migrate_secrets` at all — unlike Telegram's `botToken`
(routed through `secret-settings`, which is gated) or every credential in
`SUPPORTED_SECRET_TARGETS`. Even with `--preset user-data` alone (documented
as "excludes allowlisted secrets") and no `--migrate-secrets`,
`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`/`DISCORD_BOT_TOKEN` still landed in
`.env`. Both functions now gate the token fields behind
`self.migrate_secrets`, recording an explicit skip with the reason when
disabled; the non-secret allowlist fields (`*_ALLOWED_USERS`) still migrate
unconditionally, since those aren't credentials.

### 5. `migrate_shared_skills()` missed a custom workspace

Checked `source_root/"workspace"` and `source_root/"workspace.default"`
directly instead of going through `source_candidate()`'s custom-workspace
resolution (an `agents.defaults.workspace` pointing outside
`~/.openclaw/` — `migrate_skills()`, the sibling option, already handles
this correctly). Fixed by also checking the resolved custom workspace, plus
the post-rebrand `workspace-main`/`workspace-assistant` directory names for
consistency with `source_candidate()`.

(On our own canary this made no observable difference — the real install
has no `skills/` directory anywhere, under any workspace shape — but the
code path was still wrong for any install that does have project-level
shared skills under a custom workspace.)

### 6. `ruamel.yaml` missing: one function crashed the whole migration, others didn't

`dump_yaml_file()` raised a bare `RuntimeError` when `ruamel.yaml` isn't
installed. `run_if_selected()` only catches `ConfigReadError` (converting it
into one clean "error" item and blocking later config-mutating options via
`_config_apply_blocked`) — three call sites (`model-config`, `tts-config`,
`command-allowlist`) pre-checked `yaml is None` themselves and produced a
clean item, but roughly nine others (`mcp-servers`, `full-providers`,
`agent-config`, `gateway-config`, `deep-channels`, `browser-config`,
`tools-config`, `approvals-config`, `memory-backend`, `skills-config`,
`ui-identity`, `logging-config`) relied entirely on `dump_yaml_file()`'s
raise and would have propagated an unhandled exception straight out of
`migrate()`, crashing the run. `dump_yaml_file()` now raises
`ConfigReadError` instead, so every one of those call sites gets the same
clean handling for free. The message itself (`REASON_RUAMEL_UNAVAILABLE`,
shared by all four sites) now also says *why* this is likely happening
(running the standalone script outside the `hermes claw migrate` venv,
which always has `ruamel.yaml`) and how to fix it (`pip install
'ruamel.yaml==0.18.16'`), instead of just "ruamel.yaml is not available".

### Known follow-up not fixed in this round

A `migrated` item for an individual server/provider inside a loop (e.g.
`mcp-servers` records one "migrated" item per server as it iterates) is
recorded *before* the function's single `dump_yaml_file()` call at the end
of the loop — so if that write then raises (e.g. missing `ruamel.yaml`), the
report can show both a "migrated" item and the "error" item that
`run_if_selected()` adds for the same option, even though the write never
actually happened. `_config_apply_blocked` already prevents a *second*
config-mutating option from making the same mistake afterward, so no file
is ever corrupted — but the per-item record for the option that failed can
overstate what happened. Worth a follow-up pass through the per-item config
writers (mcp-servers, full-providers, deep-channels, ...) to only record
`migrated` after the write actually succeeds.
