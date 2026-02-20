---
description: ConfluenceページをNotebookLMのソースとして差分同期する。設定ファイルで指定されたConfluenceページを取得し、NotebookLMノートブックへ差分同期する。
argument-hint: <notebooklm名>
allowed-tools: Bash, mcp__claude_ai_Atlassian__searchConfluenceUsingCql, mcp__claude_ai_Atlassian__getConfluencePage, mcp__claude_ai_Atlassian__getPagesInConfluenceSpace, mcp__claude_ai_Atlassian__getConfluenceSpaces, mcp__notebooklm-mcp__notebook_list, mcp__notebooklm-mcp__source_list, mcp__notebooklm-mcp__source_add, mcp__notebooklm-mcp__source_delete, mcp__notebooklm-mcp__source_get
---

# confluence-to-notebooklm: Confluence → NotebookLM 差分同期

同期対象ノートブック名: $ARGUMENTS

## 概要

Confluenceのページを取得してNotebookLMのソースとして差分同期する。
設定ファイルで管理された同期対象ページのうち、前回同期以降に変更されたページのみを更新する。

---

## STEP 1: 引数バリデーションと設定ファイルの読み込み

### 1-1. 引数の確認

`$ARGUMENTS` が空の場合はエラーを表示して終了する:

```
エラー: ノートブック名を指定してください。
使用方法: /confluence-to-notebooklm <notebooklm名>

例: /confluence-to-notebooklm "設計資料"
```

### 1-2. 設定ファイルの読み込み

以下を実行して設定ファイルを読み込む:

```bash
cat ~/.config/nlm-confluence-sync/config.json 2>/dev/null
```

**設定ファイルが存在しない場合**、以下のセットアップ手順を表示して終了する:

```
初回セットアップが必要です。

設定ファイルを作成してください:

  mkdir -p ~/.config/nlm-confluence-sync

~/.config/nlm-confluence-sync/config.json を以下の内容で作成:

{
  "version": "1",
  "notebooks": {
    "<ノートブック名>": {
      "confluence": {
        "cloud_id": "<ConfluenceのCloud ID>",
        "sources": [
          { "type": "pages", "page_ids": ["<page_id_1>", "<page_id_2>"] }
        ]
      }
    }
  }
}

sources の type:
  - "pages":     特定ページIDのリストを直接指定 (page_ids が必要)
  - "space":     スペース内の全ページ (space_key が必要)
  - "page_tree": 指定ページ以下のツリー全体 (page_id が必要)
  - "cql":       CQLクエリで対象を絞る (query が必要)

Confluence の cloud_id は Atlassian 管理コンソール (admin.atlassian.com) で確認できます。
ページIDはページ URL の末尾の数字です (例: .../pages/4697849891)

設定後、再度 /confluence-to-notebooklm <ノートブック名> を実行してください。
```

**設定ファイルは存在するがノートブック名のエントリがない場合**:

```
エラー: ノートブック "<ノートブック名>" の設定が見つかりません。

~/.config/nlm-confluence-sync/config.json に "<ノートブック名>" エントリを追加してください。
```

---

## STEP 2: NotebookLM ノートブック ID の解決

`mcp__notebooklm-mcp__notebook_list` ツールを使ってノートブック一覧を取得し、`$ARGUMENTS` に一致する `title` のノートブックを探す。

**MCPツールが使えない場合**は以下のCLIコマンドにフォールバックする:
```bash
nlm notebook list --json
```

一致するノートブックが見つからない場合:

```
エラー: NotebookLM に "<ノートブック名>" という名前のノートブックが見つかりません。

利用可能なノートブック:
<ノートブック一覧>

正確な名前を指定するか、先に NotebookLM でノートブックを作成してください。
```

見つかった場合、その `id` を `NOTEBOOK_ID` として保持する。

---

## STEP 3: Confluence ページ一覧の収集

設定ファイルの `sources` 配列を順番に処理し、全ての対象ページを収集する。
各ソースタイプの処理方法:

### type: "pages"（特定ページIDリスト）

設定の `page_ids` に列挙されたIDについて、それぞれ `mcp__claude_ai_Atlassian__getConfluencePage` でページ情報を取得する。
- `cloudId`: 設定の `cloud_id`
- `pageId`: 各 page_id

取得できたページから `id`（ページID）、`title`、`version.number`（リビジョン番号）を収集する。
取得に失敗したページはスキップしてエラーログに記録する。

### type: "space"（スペース全体）

まず `mcp__claude_ai_Atlassian__getConfluenceSpaces` でスペースキーからスペースIDを解決する。
次に `mcp__claude_ai_Atlassian__getPagesInConfluenceSpace` でページ一覧を取得する。
ページネーション（cursor）を使って全ページを取得する。

### type: "page_tree"（ページツリー）

`mcp__claude_ai_Atlassian__searchConfluenceUsingCql` で以下のCQLを使用:
- CQL: `ancestor = <page_id> OR id = <page_id>`

### type: "cql"（CQLクエリ）

設定の `query` を直接 `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` に渡す。

### 収集後の処理

重複する page_id は排除し、最終的に以下の形式のマップを作成する:
```
{
  "<page_id>": { "title": "<タイトル>", "version": <バージョン番号> },
  ...
}
```

---

## STEP 4: メタデータの読み込みと差分検出

### 4-1. メタデータファイルの読み込み

```bash
cat ~/.config/nlm-confluence-sync/<NOTEBOOK_ID>.json 2>/dev/null
```

ファイルが存在しない場合は `{ "pages": {} }` として初期化する（全ページが新規扱い）。

### 4-2. NotebookLM の現在のソース一覧を取得

`mcp__notebooklm-mcp__source_list` でソース一覧を取得する（フォールバック: `nlm source list <NOTEBOOK_ID> --json`）。

タイトルが `[CONF:` で始まるソースを抽出して、NotebookLM 上の実際の状態を把握する。
（注意: `nlm source add --file` では `--title` オプションが機能せず、ファイル名がそのままタイトルになる。そのため一時ファイルのファイル名自体に `[CONF:<page_id>]` プレフィックスを含める必要がある）

### 4-3. 差分計算

以下の3種類の差分を計算する:

- **to_add**: STEP 3 のマップに存在するが、メタデータに存在しない page_id
- **to_update**: 両方に存在し、かつ STEP 3 のバージョンがメタデータの `page_version` より大きい page_id
- **to_delete**: メタデータに存在するが、STEP 3 のマップに存在しない page_id（かつ NotebookLM 上にソースが存在する）
- **unchanged**: それ以外

差分のサマリーを表示する:

```
同期対象: <ノートブック名> (ID: <NOTEBOOK_ID>)

Confluenceページ収集完了: <N>ページ
差分検出結果:
  新規追加: <N>ページ
  更新:     <N>ページ
  削除:     <N>ページ
  変更なし: <N>ページ

同期を開始します...
```

差分が全てゼロの場合（unchanged のみ）:

```
同期不要: すべてのページは最新です（<N>ページ）
最終同期: <last_synced_at>
```

---

## STEP 5: NotebookLM ソースの同期実行

**処理順序: 削除 → 更新 → 追加**（既存ソースを保護しながら処理するため）

### 5-1. 削除の実行

`to_delete` の各ページについて:
1. メタデータから `source_id` を取得
2. `mcp__notebooklm-mcp__source_delete` でソースを削除（フォールバック: `nlm source delete <source_id> -y`）
3. 成功したらメタデータから該当エントリを削除し、メタデータファイルに書き込む

### 5-2. 更新・追加の実行

`to_update` と `to_add` の各ページについて、以下の手順を実行する:

**更新の場合（to_update）:**
1. メタデータから `source_id` を取得
2. `mcp__notebooklm-mcp__source_delete` で古いソースを削除

**追加・更新共通の手順:**
1. `mcp__claude_ai_Atlassian__getConfluencePage` でページ内容を Markdown で取得
   - `contentFormat: "markdown"`
2. 以下のコマンドでページ内容を一時ファイルに保存:
   ```bash
   mkdir -p /tmp/nlm-sync
   cat > /tmp/nlm-sync/page_<page_id>.md << 'CONTENT_EOF'
   <ページの内容>
   CONTENT_EOF
   ```
   ※ ページ内容が大きい場合も安全に処理できるよう、必ず一時ファイル経由とする
   ※ **重要**: `nlm source add --file` では `--title` オプションが機能しない。ファイル名がそのままタイトルになるため、ファイル名に `[CONF:<page_id>]` プレフィックスを含める必要がある

   一時ファイルのパス: `/tmp/nlm-sync/[CONF:<page_id>] <page_title>.md`（ファイル名にページIDとタイトルを含める）

3. `mcp__notebooklm-mcp__source_add` でソースを追加:
   - `notebook_id`: `NOTEBOOK_ID`
   - `source_type`: `"file"`
   - ファイルパス: `/tmp/nlm-sync/[CONF:<page_id>] <page_title>.md`

   **MCPツールが使えない場合**のフォールバック:
   ```bash
   nlm source add <NOTEBOOK_ID> --file "/tmp/nlm-sync/[CONF:<page_id>] <page_title>.md"
   ```
4. 返却された `source_id` を取得する
   - MCPのレスポンスから直接取得する
   - フォールバック: `nlm source list <NOTEBOOK_ID> --json` で `[CONF:<page_id>]` タイトルのソースIDを特定
5. メタデータを更新してファイルに書き込む（以下の形式）:
   ```json
   {
     "version": "1",
     "notebook_id": "<NOTEBOOK_ID>",
     "notebook_name": "<ノートブック名>",
     "last_synced_at": "<現在時刻 ISO8601>",
     "pages": {
       "<page_id>": {
         "source_id": "<source_id>",
         "page_version": <バージョン番号>,
         "page_title": "<タイトル>",
         "synced_at": "<現在時刻 ISO8601>"
       }
     }
   }
   ```
   書き込みコマンド:
   ```bash
   mkdir -p ~/.config/nlm-confluence-sync
   ```
   その後、Python を使って JSON を整形して書き込む:
   ```bash
   python3 -c "import json; ..." > ~/.config/nlm-confluence-sync/<NOTEBOOK_ID>.json
   ```
6. 一時ファイルを削除:
   ```bash
   rm -f /tmp/nlm-sync/page_<page_id>.md
   ```

### 5-3. 進捗表示

各ページ処理時に進捗を表示する:

```
[1/10] 追加: [CONF:123456789] ページタイトル ... 完了
[2/10] 更新: [CONF:987654321] 別のページ ... 完了
[3/10] 削除: [CONF:111222333] 古いページ ... 完了
```

---

## STEP 6: 最終レポートと後片付け

### 6-1. 最終レポートの表示

```
同期完了: <ノートブック名>

結果サマリー:
  追加:     <N>ページ (成功: <N>, 失敗: <N>)
  更新:     <N>ページ (成功: <N>, 失敗: <N>)
  削除:     <N>ページ (成功: <N>, 失敗: <N>)
  合計:     <N>ページ管理中

<エラーがある場合:>
エラー (<N>件):
  - [CONF:<page_id>] <タイトル>: <エラー内容>
    → 次回の同期で再試行されます

メタデータ: ~/.config/nlm-confluence-sync/<NOTEBOOK_ID>.json
同期完了時刻: <ISO8601>
```

### 6-2. 後片付け

```bash
rm -rf /tmp/nlm-sync/
```

---

## エラーハンドリング方針

- **ロールバックなし**: 各ページ操作の成功時にメタデータを逐次更新する。失敗したページはメタデータに記録されないため、次回実行時に再試行される。
- **削除成功・再追加失敗**: 該当ページはソースが消えた状態になるが、次回同期で to_add として扱われ再追加される。
- **個別ページの失敗**: スキップして次のページへ進む。最終レポートでまとめて報告する。
- **Confluenceページの取得失敗**: スキップしてエラーログに記録する。

| エラー状況 | 対処 |
|-----------|------|
| `nlm` コマンドが見つからない | エラー表示して即終了 |
| NotebookLM 認証エラー | `nlm login` 実行を促して終了 |
| Confluence ページ取得失敗 | スキップ、エラー記録 |
| ソース追加失敗 | スキップ（次回再試行） |
| メタデータ書き込み失敗 | 警告を表示するが処理は継続 |
