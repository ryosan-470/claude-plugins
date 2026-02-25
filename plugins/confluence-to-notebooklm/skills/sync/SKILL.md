---
description: ConfluenceページをNotebookLMのソースとして差分同期する。設定ファイルで指定されたConfluenceページを取得し、NotebookLMノートブックへ差分同期する。
argument-hint: <notebooklm名>
allowed-tools: Bash, mcp__claude_ai_Atlassian__searchConfluenceUsingCql, mcp__claude_ai_Atlassian__getConfluencePage, mcp__claude_ai_Atlassian__getPagesInConfluenceSpace, mcp__claude_ai_Atlassian__getConfluenceSpaces
---

# confluence-to-notebooklm: Confluence → NotebookLM 差分同期

同期対象ノートブック名: $ARGUMENTS

## 概要

Python スクリプト（sync.py）がメタデータ管理・差分計算・NotebookLM 操作を担当する。
このスキルは Confluence からのページ取得（MCP 認証が必要な部分）のみを担当する。

---

## STEP 1: 引数バリデーションと sync.py の検出

### 1-1. 引数の確認

`$ARGUMENTS` が空の場合はエラーを表示して終了する:

```
エラー: ノートブック名を指定してください。
使用方法: /confluence-to-notebooklm:sync <notebooklm名>
例: /confluence-to-notebooklm:sync "設計資料"
```

### 1-2. sync.py の検出

以下のコマンドで sync.py のパスを特定する:

```bash
find ~/.claude -name sync.py -path '*/confluence-to-notebooklm/scripts/*' 2>/dev/null | head -1
```

見つからない場合:

```
エラー: sync.py が見つかりません。
プラグインが正しくインストールされているか確認してください:
  /plugin marketplace add ryosan-470/claude-plugins
```

見つかったパスを `SYNC_SCRIPT` として保持する。

---

## STEP 2: plan の実行

以下を実行する:

```bash
uv run "$SYNC_SCRIPT" plan "$ARGUMENTS"
```

出力された JSON をパースする。

**`status` が `"error"` の場合**: `error` と `hint` を表示して終了する。

**`status` が `"ok"` の場合**: 以下のフィールドを保持する:
- `notebook_id`, `notebook_name`, `cloud_id`
- `workdir`（例: `/tmp/nlm-sync-20260221T103000`）
- `sources`（取得すべきページの定義）
- `known_pages`（前回同期済みページとバージョンのマップ）

---

## STEP 3: Confluence ページの取得

`sources` 配列を順番に処理し、各ページの内容を `<workdir>/pages/<page_id>.json` に保存する。

### ページ情報の保存形式

各ページは以下の JSON 形式で保存する:

```json
{
  "page_id": "<page_id>",
  "title": "<ページタイトル>",
  "version": <バージョン番号>,
  "content_markdown": "<Markdownコンテンツ>"
}
```

保存コマンド（Python で JSON を安全に書き込む）:

```bash
python3 -c "
import json
data = {
  'page_id': '<page_id>',
  'title': '<title>',
  'version': <version>,
  'content_markdown': '''<content>'''
}
with open('<workdir>/pages/<page_id>.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
"
```

### type: "pages"（特定ページIDリスト）

`page_ids` の各 ID について `mcp__claude_ai_Atlassian__getConfluencePage` を呼び出す:
- `cloudId`: `cloud_id`
- `pageId`: 各 page_id
- `contentFormat`: `"markdown"`

レスポンスから `id`（page_id）、`title`、`version.number`（バージョン）、本文（Markdown）を取得して保存する。
取得に失敗したページはスキップする。

### type: "space"（スペース全体）

1. `mcp__claude_ai_Atlassian__getConfluenceSpaces` でスペースキーからスペース ID を解決する
2. `mcp__claude_ai_Atlassian__getPagesInConfluenceSpace` でページ一覧を取得する（ページネーション対応）
3. 各ページについて `mcp__claude_ai_Atlassian__getConfluencePage` でコンテンツを取得して保存する

### type: "page_tree"（ページツリー）

`mcp__claude_ai_Atlassian__searchConfluenceUsingCql` で検索する:
- CQL: `ancestor = <page_id> OR id = <page_id>`

各ページのコンテンツを `mcp__claude_ai_Atlassian__getConfluencePage` で取得して保存する。

### type: "cql"（CQLクエリ）

設定の `query` を `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` に渡す。
各ページのコンテンツを `mcp__claude_ai_Atlassian__getConfluencePage` で取得して保存する。

---

## STEP 4: sync の実行

以下を実行する:

```bash
uv run "$SYNC_SCRIPT" sync "$ARGUMENTS" --workdir "<workdir>"
```

出力された JSON をパースして結果を表示する:

**`status` が `"error"` の場合**: エラー内容を表示する。

**`status` が `"ok"` の場合**: 以下の形式でレポートを表示する:

```
同期完了: <notebook_name>

結果:
  追加:     <added>ページ
  更新:     <updated>ページ
  削除:     <deleted>ページ
  変更なし: <unchanged>ページ
  合計管理: <total_managed>ページ
  同期時刻: <synced_at>

<errors が空でない場合>
エラー (<N>件):
  - [CONF:<page_id>] <title>: <error>
    → 次回の同期で再試行されます
```
