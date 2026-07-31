---
description: Mandatory development cycle rule requiring version bumps, changelog updates, README updates, and llm-wiki-kb maintenance.
mode: subagent
---

# Development Cycle Documentation & Versioning Rule

You are an automated software engineering assistant working on AutoRB. 
CRITICAL MANDATE: During every development cycle where code, pipelines, packaging logic, or configuration scripts are modified, you MUST proactively and thoroughly:
1. Bump the pipeline version in `/workspaces/RockBandAutoSongLevelCreator/autorb/version.py` by incrementing it by `0.0001`.
2. Document all changes in `/workspaces/RockBandAutoSongLevelCreator/CHANGELOG.md` under the new version.
3. Update `/workspaces/RockBandAutoSongLevelCreator/README.md` to reflect new features, test commands, or pipeline changes.
4. Update `/workspaces/RockBandAutoSongLevelCreator/llm-wiki-kb/` to keep architectural records and domain knowledge completely up-to-date.

Never skip version bumps, changelog entries, or documentation updates when completing tasks.
