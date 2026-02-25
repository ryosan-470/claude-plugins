# claude-plugins

Custom Claude Code plugin marketplace.

## Installation

```
/plugin marketplace add ryosan-470/claude-plugins
```

## Plugins

### confluence-to-notebooklm (v2.2.0)

Confluence ページを NotebookLM のソースとして差分同期するスキル。

#### Prerequisites

- [Atlassian MCP](https://github.com/anthropics/claude-code) (Confluence API アクセス用)
- [uv](https://docs.astral.sh/uv/) (スクリプト実行・依存解決に使用、`notebooklm-mcp-cli` は自動インストール)

#### Setup

Claude Code 上でプラグインをインストールします。

```
/plugin install confluence-to-notebooklm@ryosan-470-plugins
```

##### 対話的セットアップ（推奨）

setup スキルで Confluence ソースを対話的に選択し、設定ファイルを自動生成できます:

```
/confluence-to-notebooklm:setup "設計資料"
```

Cloud ID の自動検出、スペース/ページのブラウズ、CQL クエリのプレビューに対応しています。

##### 手動セットアップ

手動で設定ファイルを作成する場合:

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
/confluence-to-notebooklm 設計資料
```

差分検出により、前回同期以降に更新されたページのみが同期されます。
