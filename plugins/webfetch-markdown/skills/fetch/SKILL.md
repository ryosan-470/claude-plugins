---
description: URLのHTMLをMarkdown/プレーンテキストに変換してコンテキストに渡す。WebFetchのHaiku要約をバイパスして生のページ内容を取得する。curl失敗時はWebFetchにフォールバック。
argument-hint: <URL> [--more]
allowed-tools: Bash, WebFetch
model: haiku
---

# webfetch-markdown:fetch — 生ページ内容をMarkdownで取得

WebFetch と異なり、Haiku による要約は行わず生の変換済みコンテンツをそのままコンテキストに渡す。

## STEP 1: 引数の解析

引数全体を `$ARGUMENTS` として受け取る。

```bash
ARGUMENTS="$ARGUMENTS"  # スキルランタイムが注入
```

`--more` フラグの有無を確認する:

- 引数が `--more` で終わっている場合: `MORE_MODE=true`、URLは `--more` を除いた残りの部分
- それ以外: `MORE_MODE=false`、URLは引数全体

URLが空、または `http://` / `https://` で始まらない場合は以下を表示して終了する:

```
エラー: URLを指定してください。
使用方法: /webfetch-markdown:fetch <URL> [--more]
例: /webfetch-markdown:fetch https://example.com
```

## STEP 2: キャッシュファイルパスの計算

URLのSHA256ハッシュ (先頭16文字) を使ってキャッシュパスを決定する:

```bash
URL_HASH=$(echo -n "$URL" | sha256sum 2>/dev/null | cut -c1-16 \
           || echo -n "$URL" | shasum -a 256 2>/dev/null | cut -c1-16 \
           || python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" "$URL")
CACHE_MD="/tmp/wfm-${URL_HASH}.md"
CACHE_OFFSET="/tmp/wfm-${URL_HASH}.offset"
```

## STEP 3: --more モードの処理

`MORE_MODE=true` の場合:

1. `$CACHE_MD` が存在しないなら以下を表示して終了:
   ```
   ⚠️ キャッシュが見つかりません。--more なしで再実行してください:
   /webfetch-markdown:fetch <URL>
   ```

2. `$CACHE_OFFSET` から現在のオフセット (バイト) を読み込む。ファイルがなければ `0`。

3. オフセット位置から 51200 バイト (50KB) を読み出す:
   ```bash
   CHUNK=$(dd if="$CACHE_MD" bs=1 skip="$OFFSET" count=51200 2>/dev/null)
   ```

4. 実際に読み出せたバイト数を計算し、新しいオフセット = 旧オフセット + 読み出しバイト数 を `$CACHE_OFFSET` に書く。

5. STEP 7 の出力フォーマットに従いチャンクを出力する。

6. 新オフセット < ファイル全体のサイズなら末尾に以下を追加:
   ```
   ⚠️ [TRUNCATED] 全 YY KB 中 ZZ KB まで表示。続きは:
   /webfetch-markdown:fetch <URL> --more
   ```
   全て表示し終えた場合はキャッシュファイル (`$CACHE_MD`, `$CACHE_OFFSET`) を削除する。

7. **ここで処理を終了する (以降の STEP は実行しない)**。

## STEP 4: HTML の取得 (curl)

```bash
HTML=$(curl -sL \
  --max-time 30 \
  --max-filesize 5242880 \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: ja,en-US;q=0.9,en;q=0.8" \
  --fail \
  "$URL" 2>/tmp/wfm-curl-err.txt)
CURL_EXIT=$?
```

`CURL_EXIT` が 0 以外の場合: STEP 6 (WebFetch フォールバック) へ進む。

## STEP 5: Markdown 変換

以下の優先順で変換ツールを検出し、最初に見つかったものを使用する。変換結果を `CONVERTED` 変数に格納し、使用したツール名を `TOOL_USED` に記録する。

### 優先度 1: pandoc

```bash
if command -v pandoc >/dev/null 2>&1; then
  CONVERTED=$(echo "$HTML" | pandoc -f html -t markdown --wrap=none 2>/dev/null)
  TOOL_USED="pandoc"
fi
```

### 優先度 2: html2text (uv 経由)

```bash
elif command -v uv >/dev/null 2>&1; then
  CONVERTED=$(echo "$HTML" | uv run --quiet --with html2text python -m html2text 2>/dev/null)
  TOOL_USED="html2text (uv)"
fi
```

### 優先度 3: python3 内蔵フォールバック (常に利用可能)

```bash
else
  CONVERTED=$(echo "$HTML" | python3 -c "
import sys, re
text = sys.stdin.read()
text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
text = re.sub(r'<[^>]+>', '', text)
text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
           .replace('&nbsp;', ' ').replace('&#39;', \"'\").replace('&quot;', '\"') \
           .replace('&apos;', \"'\")
text = re.sub(r'\n{3,}', '\n\n', text)
print(text.strip())
")
  TOOL_USED="python3 (内蔵)"
fi
```

## STEP 6: WebFetch フォールバック

STEP 4 で `CURL_EXIT` が 0 以外だった場合 (curl 失敗時のみこのステップを実行):

```
⚠️ curl が失敗しました (終了コード: $CURL_EXIT)。
   $(cat /tmp/wfm-curl-err.txt 2>/dev/null)
   WebFetch にフォールバックします...
```

WebFetch ツールを使って `$URL` の内容を取得して返す。**その後このスキルの処理を終了する。**

## STEP 7: JS 依存サイトの検出

`CONVERTED` のバイト数が 1024 未満の場合:

```
⚠️ [JS-DEPENDENT] 取得したコンテンツが非常に少量 (X バイト) です。
   このサイトはJavaScriptで動的にコンテンツを生成している可能性があります。
   curlは静的HTMLのみ取得するため、SPAや動的サイトでは内容が取得できません。
```

## STEP 8: キャッシュ書き込みとサイズチェック

変換済みコンテンツをキャッシュに保存する:

```bash
echo "$CONVERTED" > "$CACHE_MD"
TOTAL_BYTES=$(wc -c < "$CACHE_MD")
TOTAL_KB=$(( TOTAL_BYTES / 1024 ))
```

サイズに応じて処理を分岐する:

### 50KB 以下の場合

全文を出力し、キャッシュファイルを削除する:

```bash
rm -f "$CACHE_MD" "$CACHE_OFFSET"
CHUNK="$CONVERTED"
PAGE_INFO="全 ${TOTAL_KB} KB (全文)"
NEEDS_MORE=false
```

### 50KB 超の場合

先頭 51200 バイトのみを出力し、オフセットを記録する:

```bash
CHUNK=$(dd if="$CACHE_MD" bs=1 count=51200 2>/dev/null)
echo "51200" > "$CACHE_OFFSET"
PAGE_INFO="全 ${TOTAL_KB} KB 中先頭 50 KB"
NEEDS_MORE=true
```

## STEP 9: 出力

以下のフォーマットで出力する:

```
# ページ内容: <URL>
取得日時: <date -u +"%Y-%m-%dT%H:%M:%SZ">
変換ツール: <TOOL_USED>
サイズ: <PAGE_INFO>

---

<CHUNK の内容>
```

`NEEDS_MORE=true` の場合、末尾に以下を追加する:

```
---
⚠️ [TRUNCATED] 全 YY KB 中先頭 50 KB を表示。続きを取得するには:
/webfetch-markdown:fetch <URL> --more
```
