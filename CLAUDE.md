# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Custom Claude Code plugin marketplace (`ryosan-470/claude-plugins`). This is a private repository — `GITHUB_TOKEN` or `GH_TOKEN` environment variable is required for access. There is no build system, test suite, or linter — all plugins are defined entirely as JSON metadata + Markdown skill specifications.

Install the marketplace:
```
/plugin marketplace add ryosan-470/claude-plugins
```

## Architecture

The repository has two layers:

1. **Marketplace level** (root): `.claude-plugin/marketplace.json` registers all plugins and points to their source directories under `plugins/`.
2. **Plugin level** (`plugins/<name>/`): Each plugin contains `.claude-plugin/plugin.json` (metadata) and one or more skills in `skills/<skill-name>/SKILL.md`.

### Skill Files (SKILL.md)

Skills are the core implementation unit. Each SKILL.md is a Markdown file with:
- **YAML frontmatter**: `description`, `argument-hint`, and `allowed-tools` (whitelists which Claude Code tools and MCP tools the skill may use)
- **Body**: Step-by-step procedural specification that Claude Code follows at runtime. This is not documentation — it is the executable implementation.

Skills interact with external services via MCP tool names (e.g., `mcp__claude_ai_Atlassian__getConfluencePage`, `mcp__notebooklm-mcp__source_add`) with CLI fallback commands when MCP is unavailable.

## Adding a New Plugin

1. Create `plugins/<plugin-name>/.claude-plugin/plugin.json` with `name`, `description`, `version`
2. Create `plugins/<plugin-name>/skills/<skill-name>/SKILL.md` with frontmatter and implementation steps
3. Register in `.claude-plugin/marketplace.json` under the `plugins` array (include `name`, `source`, `description`, `version`, `keywords`, `category`)