# claude-plugins

Custom Claude Code plugin marketplace.

## Installation

```
/plugin marketplace add ryosan-470/claude-plugins
```

Private repository のため、`GITHUB_TOKEN` or `GH_TOKEN` 環境変数の設定が必要です。

## Plugins

### sync-notebooklm

Confluence ページを NotebookLM のソースとして差分同期するスキル。

```
/sync-notebooklm <notebooklm名>
```

#### Prerequisites

- [Atlassian MCP](https://github.com/anthropics/claude-code) (Confluence API アクセス用)
- [NotebookLM MCP](https://github.com/notebooklm-mcp/notebooklm-mcp) (`notebooklm-mcp`)
- `nlm` CLI (MCP フォールバック用、任意)

#### Setup

初回実行時に設定ファイルの作成が必要です:

```bash
mkdir -p ~/.config/nlm-confluence-sync
```

`~/.config/nlm-confluence-sync/config.json`:

```json
{
  "version": "1",
  "notebooks": {
    "<NotebookLM上のノートブック名>": {
      "confluence": {
        "cloud_id": "<ConfluenceのCloud ID>",
        "sources": [
          {
            "type": "pages",
            "page_ids": ["<page_id_1>", "<page_id_2>"]
          }
        ]
      }
    }
  }
}
```

##### Source types

| type | description | required field |
|------|-------------|---------------|
| `pages` | 特定ページ ID のリストを直接指定 | `page_ids` |
| `space` | スペース内の全ページ | `space_key` |
| `page_tree` | 指定ページ以下のツリー全体 | `page_id` |
| `cql` | CQL クエリで対象を絞る | `query` |

##### How to find IDs

- **Cloud ID**: Atlassian 管理コンソール (admin.atlassian.com) で確認
- **Page ID**: ページ URL の末尾の数字 (例: `.../pages/4697849891`)

#### Usage

```
/sync-notebooklm 設計資料
```

差分検出により、前回同期以降に更新されたページのみが同期されます。
