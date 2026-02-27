---
description: ConfluenceページをNotebookLMのソースとして差分同期する。設定ファイルで指定されたConfluenceページを取得し、NotebookLMノートブックへ差分同期する。
argument-hint: <notebooklm名>
allowed-tools: Bash, Write, mcp__claude_ai_Atlassian__searchConfluenceUsingCql, mcp__claude_ai_Atlassian__fetch, mcp__claude_ai_Atlassian__getPagesInConfluenceSpace, mcp__claude_ai_Atlassian__getConfluenceSpaces
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
  "version": <バージョン番号（取得できない場合は 0）>,
  "content_markdown": "<Markdownコンテンツ>"
}
```

**注意**: `version` は変更検出のキーとなる値である。`mcp__claude_ai_Atlassian__fetch` の `metadata.version` を必ず設定すること。

**重要: 保存には必ず Write ツールを使用すること。**

MCP レスポンスの `text` フィールドの内容を**一切要約・省略せずにそのまま** JSON に含めること。
`python3 -c` やシェルの heredoc を使うと、コンテンツがシェル文字列に埋め込まれる過程で要約・劣化するため使用禁止。

Write ツールで `<workdir>/pages/<page_id>.json` に以下の JSON 文字列を書き込む:

```json
{"page_id": "<page_id>", "title": "<title>", "version": <metadata.versionの値>, "content_markdown": "<textフィールドの内容をそのまま>"}
```

各ページの MCP レスポンスを受け取ったら、1ページずつ即座に Write ツールで保存すること。

### type: "pages"（特定ページIDリスト）

`page_ids` の各 ID について `mcp__claude_ai_Atlassian__fetch` を呼び出す:
- `id`: `ari:cloud:confluence:<cloud_id>:page/<page_id>`

レスポンスから `title`、`text`（Markdown本文）、`metadata.version` を取得して保存する。
取得に失敗したページはスキップする。

### type: "space"（スペース全体）

1. `mcp__claude_ai_Atlassian__getConfluenceSpaces` でスペースキーからスペース ID を解決する
2. `mcp__claude_ai_Atlassian__getPagesInConfluenceSpace` でページ一覧を取得する（ページネーション対応）
3. 各ページについて `mcp__claude_ai_Atlassian__fetch` で `id`: `ari:cloud:confluence:<cloud_id>:page/<page_id>` を指定してコンテンツを取得して保存する

### type: "page_tree"（ページツリー）

`mcp__claude_ai_Atlassian__searchConfluenceUsingCql` で検索する:
- CQL: `ancestor = <page_id> OR id = <page_id>`

各ページのコンテンツを `mcp__claude_ai_Atlassian__fetch` で `id`: `ari:cloud:confluence:<cloud_id>:page/<page_id>` を指定して取得して保存する。

### type: "cql"（CQLクエリ）

設定の `query` を `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` に渡す。
各ページのコンテンツを `mcp__claude_ai_Atlassian__fetch` で `id`: `ari:cloud:confluence:<cloud_id>:page/<page_id>` を指定して取得して保存する。

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
