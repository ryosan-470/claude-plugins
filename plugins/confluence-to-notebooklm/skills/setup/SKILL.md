---
description: Confluence→NotebookLM同期の設定ファイルを対話的に作成・更新する。Cloud IDやソースをMCP経由で自動検出し、config.jsonを生成する。
argument-hint: <notebooklm名>
allowed-tools: Bash, Read, Write, AskUserQuestion, mcp__claude_ai_Atlassian__getAccessibleAtlassianResources, mcp__claude_ai_Atlassian__getConfluenceSpaces, mcp__claude_ai_Atlassian__getPagesInConfluenceSpace, mcp__claude_ai_Atlassian__searchConfluenceUsingCql, mcp__claude_ai_Atlassian__getConfluencePageDescendants, mcp__claude_ai_Atlassian__getConfluencePage
---

# confluence-to-notebooklm: 設定セットアップ

対象ノートブック名: $ARGUMENTS

## 概要

対話的に Confluence ソースを選択し、`~/.config/nlm-confluence-sync/config.json` を作成・更新する。
既存の設定ファイルがある場合は、指定されたノートブックのエントリのみを追加・上書きする。

---

## STEP 1: 引数バリデーション

`$ARGUMENTS` が空の場合はエラーを表示して終了する:

```
エラー: ノートブック名を指定してください。
使用方法: /confluence-to-notebooklm:setup <notebooklm名>
例: /confluence-to-notebooklm:setup "設計資料"
```

以降、`$ARGUMENTS` の値を `NOTEBOOK_NAME` として参照する。

---

## STEP 2: 既存設定の確認

Read ツールで `~/.config/nlm-confluence-sync/config.json` の内容を確認する。

### ファイルが存在する場合

JSON をパースして `EXISTING_CONFIG` として保持する。
`NOTEBOOK_NAME` のエントリが既に存在する場合、既存のソース一覧を表示したうえで AskUserQuestion で確認する:

```
「<NOTEBOOK_NAME>」の設定が既に存在します（ソース <N> 件）:
  - <type>: <概要>
  - ...

どうしますか？

1. ソースを追加する（既存のソースを保持したまま追加）
2. 上書きする（既存のソース設定を置き換える）
3. キャンセル
```

- 「ソースを追加する」の場合: 既存の `sources` 配列を `EXISTING_SOURCES` として保持し、STEP 4 で追加されたソースをマージする
- 「上書きする」の場合: `EXISTING_SOURCES` を空にして STEP 3 から新規作成する
- 「キャンセル」の場合は終了する

### ファイルが存在しない場合

`EXISTING_CONFIG` を以下の初期値に設定する:

```json
{
  "version": "1",
  "notebooks": {}
}
```

---

## STEP 3: Cloud ID の自動検出

`mcp__claude_ai_Atlassian__getAccessibleAtlassianResources` を呼び出してアクセス可能な Atlassian リソースを取得する。

### リソースが 1 つの場合

その `id`（Cloud ID）と `name`（サイト名）を自動選択し、ユーザーに通知する:

```
Atlassian サイトを検出しました: <name> (Cloud ID: <id>)
```

### リソースが複数の場合

AskUserQuestion で選択肢を提示する:

```
複数の Atlassian サイトが見つかりました。使用するサイトを選んでください:

1. <name1> (<url1>)
2. <name2> (<url2>)
```

### リソースが 0 件の場合

エラーを表示して終了する:

```
エラー: アクセス可能な Atlassian サイトが見つかりません。
Atlassian MCP の接続設定を確認してください。
```

選択された Cloud ID を `CLOUD_ID` として保持する。

---

## STEP 4: ソースの選択（対話ループ）

ソースリストを空で初期化する: `SOURCES = []`

以下のループを繰り返す:

### 4-1. ソースタイプの選択

AskUserQuestion で以下を表示:

```
同期する Confluence ソースのタイプを選んでください:

1. pages     - 特定ページを個別に選択
2. space     - スペース全体を同期
3. page_tree - 指定ページ以下のツリー全体
4. cql       - CQL クエリで対象を指定
```

選択されたタイプに応じて 4-2 〜 4-5 のいずれかを実行する。

### 4-2. type: "pages" の場合

ページの指定方法を AskUserQuestion で確認する:

```
ページの指定方法を選んでください:

1. スペースを選んでからページを選択
2. ページタイトルで検索
3. ページ ID を直接入力
4. Confluence URL を貼り付ける
```

#### 選択肢 1: スペースからページを選択

1. `mcp__claude_ai_Atlassian__getConfluenceSpaces` で `cloudId: CLOUD_ID` を指定してスペース一覧を取得する
2. AskUserQuestion でスペースを選択させる
3. 選択されたスペースの ID で `mcp__claude_ai_Atlassian__getPagesInConfluenceSpace` を呼び出してページ一覧を取得する（limit: 50）
4. AskUserQuestion でページを選択させる（複数選択可）

#### 選択肢 2: タイトルで検索

1. AskUserQuestion で検索キーワードを入力させる
2. `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` で `cql: title ~ "<keyword>"` を実行する
3. 結果を AskUserQuestion で選択させる（複数選択可）

#### 選択肢 3: ID を直接入力

1. AskUserQuestion でページ ID を入力させる（カンマ区切りで複数指定可）

#### 選択肢 4: Confluence URL を貼り付ける

1. AskUserQuestion で Confluence URL を入力させる（スペースまたはカンマ区切りで複数指定可）

2. 各 URL からページ ID を抽出する。URL は以下の 2 形式をサポートする:

   **通常 URL** (`/wiki/spaces/<space>/pages/<page_id>` 形式):
   - パスからページ ID（数値部分）を直接抽出する。
   - 例: `https://example.atlassian.net/wiki/spaces/WEB/pages/4891902529` → `4891902529`

   **短縮 URL** (`/wiki/x/<encoded>` 形式、tiny link):
   - `<encoded>` 部分を base64 デコードし、**リトルエンディアン**の整数として解釈してページ ID を得る。
   - Bash で以下のコマンドを実行する:
     ```bash
     python3 -c "
     import base64, sys
     encoded = sys.argv[1]
     # base64 パディングを補完
     padded = encoded + '=' * (-len(encoded) % 4)
     decoded_bytes = base64.b64decode(padded)
     page_id = int.from_bytes(decoded_bytes, 'little')
     print(page_id)
     " "<encoded>"
     ```
   - 例: `https://example.atlassian.net/wiki/x/5QK1HQE` → encoded=`5QK1HQE` → `4793369317`

3. 各ページ ID について `mcp__claude_ai_Atlassian__getConfluencePage` で検証し、タイトルを表示して確認する:
   ```
   URL から以下のページを検出しました:
     - <page_id1>: <title1>
     - <page_id2>: <title2>
   ```
   検証に失敗したページ ID はスキップし、ユーザーに通知する。

選択されたページ ID を `SOURCES` に追加:

```json
{"type": "pages", "page_ids": ["<id1>", "<id2>"]}
```

### 4-3. type: "space" の場合

1. `mcp__claude_ai_Atlassian__getConfluenceSpaces` で `cloudId: CLOUD_ID` を指定してスペース一覧を取得する
2. AskUserQuestion でスペースを選択させる

`SOURCES` に追加:

```json
{"type": "space", "space_key": "<selected_space_key>"}
```

### 4-4. type: "page_tree" の場合

ルートページの指定方法を AskUserQuestion で確認する（4-2 と同様の 4 択、ただし選択は 1 ページのみ）。

選択後、`mcp__claude_ai_Atlassian__getConfluencePageDescendants` でルートページの子ページを取得し、ツリーの概要を表示する:

```
ページツリーのプレビュー:
  <root_title>
  ├── <child_title1>
  ├── <child_title2>
  │   └── <grandchild_title1>
  └── <child_title3>
合計: <N> ページ
```

AskUserQuestion で確認:

```
このページツリーを同期対象にしますか？

1. はい
2. いいえ（やり直す）
```

「はい」の場合、`SOURCES` に追加:

```json
{"type": "page_tree", "page_id": "<root_page_id>"}
```

「いいえ」の場合は 4-4 の先頭に戻る。

### 4-5. type: "cql" の場合

1. AskUserQuestion で CQL クエリを入力させる:

```
CQL クエリを入力してください:
例: label = "design-doc" AND space = "TEAM"
参考: https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/
```

2. 入力されたクエリを `mcp__claude_ai_Atlassian__searchConfluenceUsingCql` で実行してプレビューする:

```
CQL クエリの結果（<N> 件）:
  1. <title1> (ID: <id1>)
  2. <title2> (ID: <id2>)
  ...
```

3. AskUserQuestion で確認:

```
この CQL クエリを同期対象にしますか？

1. はい
2. いいえ（クエリを修正する）
```

「いいえ」の場合は 4-5 の先頭に戻る。
「はい」の場合、`SOURCES` に追加:

```json
{"type": "cql", "query": "<CQLクエリ>"}
```

### 4-6. ソース追加の継続確認

現在のソース設定を人間が読みやすい形式で表示し、AskUserQuestion で確認:

```
別のソースを追加しますか？

1. はい（別のソースを追加する）
2. いいえ（設定を完了する）
```

「はい」の場合は 4-1 に戻る。「いいえ」の場合は STEP 5 へ進む。

---

## STEP 5: 設定ファイルの書き込み

### 5-1. ディレクトリの作成

```bash
mkdir -p ~/.config/nlm-confluence-sync
```

### 5-2. 設定の組み立て

STEP 2 で「ソースを追加する」が選択されていた場合は、`EXISTING_SOURCES` と STEP 4 で収集した `SOURCES` を結合する:
`FINAL_SOURCES = EXISTING_SOURCES + SOURCES`

それ以外の場合は `FINAL_SOURCES = SOURCES` とする。

`EXISTING_CONFIG` の `notebooks` に以下のエントリを追加（または上書き）する:

```json
{
  "<NOTEBOOK_NAME>": {
    "confluence": {
      "cloud_id": "<CLOUD_ID>",
      "sources": <FINAL_SOURCES>
    }
  }
}
```

### 5-3. ファイルの書き込み

Write ツールで `~/.config/nlm-confluence-sync/config.json` に設定を書き込む。
JSON は `indent: 2`, `ensure_ascii: false` で整形する。

---

## STEP 6: 完了メッセージ

以下の形式で結果を表示する:

```
設定が完了しました！

ノートブック: <NOTEBOOK_NAME>
Cloud ID:    <CLOUD_ID>
ソース数:    <SOURCES の要素数>
設定ファイル: ~/.config/nlm-confluence-sync/config.json

同期を実行するには:
  /confluence-to-notebooklm <NOTEBOOK_NAME>
```
