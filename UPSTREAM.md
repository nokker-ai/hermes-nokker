# Upstream

| | |
|---|---|
| Project | Hermes Agent (Nous Research), MIT |
| URL | https://github.com/NousResearch/hermes-agent |
| Pinned tag | `v0.22.2` |
| Pinned commit | `d923a5eb487a17c0a68801bba9ef0f56c81040a8` |
| Upstream release date | 2026-10-15 |
| Pinned on | 2026-10-16 |

Branches:

- `vendor/hermes` = upstream, pinned. Never commit our changes there; it only moves on a deliberate rebase.
- `main` = Nokker. Every replacement of a Hermes subsystem goes through a provider interface so that the
  vendor part stays rebaseable (roadmap §3.1). Hard fork decision at M3.

Rebase procedure (quarterly, not during P0): fetch `upstream`, fast-forward `vendor/hermes` to the new tag,
rebase or merge `main`, run the bench (`bench/`) and the canary before promoting.
