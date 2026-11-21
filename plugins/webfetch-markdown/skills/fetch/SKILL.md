---
description: URLのHTMLをMarkdown/プレーンテキストに変換してコンテキストに渡す。Omniroute (ANTHROPIC_BASE_URL) 環境では /api/v1/web/fetch を使い、未使用時は curl / w3m / python3 で取得する。WebFetchは使わない。
argument-hint: <URL> [--more] [--direct]
allowed-tools: Bash
---

# webfetch-markdown:fetch — 生ページ内容をMarkdownで取得

WebFetch と異なり、Haiku による要約は行わず生の変換済みコンテンツをそのままコンテキストに渡す。

**WebFetch へはフォールバックしない。** Anthropic 互換プロキシ (`ANTHROPIC_BASE_URL` が設定されている環境) では、WebFetch の内部処理が `haiku` に解決され、プロキシ側の haiku combo が失敗すると 403 で即座に落ちる。原因の分かりにくい失敗を避けるため、このスキルはローカルの取得経路だけで完結する。

取得経路は 2 系統:

| 状況 | 経路 |
| --- | --- |
| Omniroute が応答する | `POST $ANTHROPIC_BASE_URL/api/v1/web/fetch` (`format: markdown`) |
| それ以外 / `--direct` 指定 | `curl` → `w3m` → `python3 urllib` |

## STEP 1: 引数の解析

引数全体を `$ARGUMENTS` として受け取る。

```bash
ARGUMENTS="$ARGUMENTS"  # スキルランタイムが注入
```

トークンに分解し、フラグを抽出する:

- `--more`: `MORE_MODE=true`
- `--direct`: `DIRECT_MODE=true` (Omniroute を使わず curl 系のみ)
- フラグ以外の最初のトークンが `URL`

URLが空、または `http://` / `https://` で始まらない場合は以下を表示して終了する:

```
エラー: URLを指定してください。
使用方法: /webfetch-markdown:fetch <URL> [--more] [--direct]
例: /webfetch-markdown:fetch https://example.com
```

## STEP 2: キャッシュファイルパスの計算

URLのSHA256ハッシュ (先頭16文字) を使ってキャッシュパスを決定する:

```bash
URL_HASH=$(echo -n "$URL" | sha256sum 2>/dev/null | cut -c1-16 \
           || echo -n "$URL" | shasum -a 256 2>/dev/null | cut -c1-16 \
           || python3 -I -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" "$URL")
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

5. STEP 11 の出力フォーマットに従いチャンクを出力する。

6. 新オフセット < ファイル全体のサイズなら末尾に以下を追加:
   ```
   ⚠️ [TRUNCATED] 全 YY KB 中 ZZ KB まで表示。続きは:
   /webfetch-markdown:fetch <URL> --more
   ```
   全て表示し終えた場合はキャッシュファイル (`$CACHE_MD`, `$CACHE_OFFSET`) を削除する。

7. **ここで処理を終了する (以降の STEP は実行しない)**。

## STEP 4: Omniroute の判定

Omniroute が使われているかを、専用 API の存在で判定する。単に `ANTHROPIC_BASE_URL` があるだけでは判定しない (素の Anthropic API や別プロキシの可能性があるため)。

```bash
BASE_URL="${WEBFETCH_BASE_URL:-${ANTHROPIC_BASE_URL:-}}"
BASE_URL="${BASE_URL%/}"

AUTH_HEADER=()
if [ -n "${OMNIROUTE_API_KEY:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${OMNIROUTE_API_KEY}")
elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${ANTHROPIC_AUTH_TOKEN}")
fi

USE_OMNIROUTE=false
if [ "$DIRECT_MODE" != "true" ] && [ -n "$BASE_URL" ]; then
  PROBE=$(mktemp /tmp/wfm-probe-XXXXXX)
  PROBE_CODE=$(curl -sS --max-time 5 -o "$PROBE" -w '%{http_code}' \
    "${AUTH_HEADER[@]}" "$BASE_URL/api/v1/search" 2>/dev/null)
  if [ "$PROBE_CODE" = "200" ] && \
     jq -e '.object == "list" and ([.data[]? | select(.object == "search_provider")] | length > 0)' \
       "$PROBE" >/dev/null 2>&1; then
    USE_OMNIROUTE=true
  fi
  rm -f "$PROBE"
fi
```

- `USE_OMNIROUTE=true` → STEP 5 へ
- `USE_OMNIROUTE=false` → STEP 6 へ

## STEP 5: Omniroute API で取得

```bash
OMNI_TMP=$(mktemp /tmp/wfm-omni-XXXXXX)
OMNI_CODE=$(curl -sS --max-time 90 -o "$OMNI_TMP" -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/web/fetch" \
  -H 'content-type: application/json' \
  "${AUTH_HEADER[@]}" \
  -d "$(jq -n --arg url "$URL" '{url: $url, format: "markdown", include_metadata: true}')" \
  2>/tmp/wfm-omni-err.txt)
OMNI_CONTENT=$(jq -r '.content // empty' "$OMNI_TMP" 2>/dev/null)
```

`OMNI_CODE` が 200 かつ `OMNI_CONTENT` が空でない場合、取得成功:

```bash
CONVERTED="$OMNI_CONTENT"
TOOL_USED="omniroute:$(jq -r '.provider // "unknown"' "$OMNI_TMP")"
PAGE_TITLE=$(jq -r '.metadata.title // empty' "$OMNI_TMP")
rm -f "$OMNI_TMP"
```

**この場合は STEP 8 (Markdown 変換) をスキップして STEP 9 へ進む。** API がすでに Markdown を返しているため。

失敗した場合 (`OMNI_CODE` ≠ 200、または `.content` が空) は警告を出して STEP 6 へ進む:

```
⚠️ Omniroute /api/v1/web/fetch で取得できませんでした (HTTP <OMNI_CODE>)。
   <jq -r '.error.message // .message // empty' の結果、または /tmp/wfm-omni-err.txt>
   直接取得 (curl) にフォールバックします...
```

```bash
rm -f "$OMNI_TMP"
```

補足:

- `format` は `markdown` / `html` / `links` / `screenshot` を指定できるが、このスキルでは常に `markdown` を使う
- `include_metadata: true` で `.metadata.title` などが入る
- HTTP 200 でも `.content` が空のことがある (`ftp://` など)。必ず content の有無で判定する
- 認証は `OMNIROUTE_API_KEY` (Omniroute の API キー) を `Authorization: Bearer` で送る。未設定ならヘッダーなし (localhost の既定構成では不要)

## STEP 6: curl で直接取得

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

`CURL_EXIT` が 0 なら STEP 8 (Markdown 変換) へ、0 以外なら STEP 7 へ進む。

## STEP 7: ローカル代替取得 (w3m / python3)

STEP 6 で `CURL_EXIT` が 0 以外だった場合のみ実行する。

### 7-1: 失敗内容の表示

```
⚠️ curl が失敗しました (終了コード: $CURL_EXIT)。
   $(cat /tmp/wfm-curl-err.txt 2>/dev/null)
   代替の取得手段を試します...
```

### 7-2: w3m (インストール済みの場合)

`w3m` は HTML の取得とテキスト化を自前で行うため、成功した場合は STEP 8 の変換をスキップして STEP 9 へ進む。

```bash
FETCH_OK=false
if command -v w3m >/dev/null 2>&1; then
  CONVERTED=$(w3m -dump -cols 120 -T text/html "$URL" 2>/dev/null)
  if [ -n "$CONVERTED" ]; then
    TOOL_USED="w3m"
    FETCH_OK=true
  fi
fi
```

`FETCH_OK=true` なら STEP 9 へ進む。

### 7-3: python3 urllib (curl とは別の TLS / HTTP 実装)

```bash
HTML=$(python3 -I - "$URL" 2>/dev/null <<'PY'
import gzip
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
})
with urllib.request.urlopen(req, timeout=30) as res:
    data = res.read(5 * 1024 * 1024)
    if res.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    sys.stdout.buffer.write(data)
PY
)
```

`HTML` が空でなければ STEP 8 (Markdown 変換) へ進む。

### 7-4: すべて失敗した場合

以下を表示して終了する (**WebFetch は呼ばない**):

```
❌ ページを取得できませんでした: <URL>

   取得経路:
     Omniroute web/fetch : <USE_OMNIROUTE=true なら "失敗" / false なら "未使用">
     curl                : exit=<CURL_EXIT> $(cat /tmp/wfm-curl-err.txt 2>/dev/null)
     w3m                 : $(command -v w3m >/dev/null 2>&1 && echo "失敗" || echo "未インストール")
     python3             : 失敗

確認事項:
  - URL とネットワーク到達性 (プロキシ / VPN の影響を含む)
  - 認証が必要なページではないか (401 / 403)
  - curl の終了コード 22 は HTTP 4xx/5xx、28 はタイムアウト、6 は名前解決失敗
  - Omniroute 環境なら次で取得系 API の状態を確認できる:
      curl -s <BASE_URL>/api/v1/search | jq '.data[].id'
  - ANTHROPIC_BASE_URL が設定された環境では WebFetch を使用しないこと。
    WebFetch の内部処理は haiku に解決され、プロキシ側の haiku combo が
    壊れていると 403 (authentication_rejected) で即座に失敗する。

代替手段:
  - ブラウザ系 MCP (chrome-devtools など) でレンダリング後の内容を取得する
  - 検索だけが目的なら /websearch-fallback:search <query> を使う
```

## STEP 8: Markdown 変換 (HTML を取得した経路のみ)

STEP 6 または STEP 7-3 で HTML を取得した場合のみ実行する。STEP 5 (Omniroute) と STEP 7-2 (w3m) はスキップする。

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
  CONVERTED=$(echo "$HTML" | python3 -I -c "
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

変換結果が空の場合は STEP 7-4 と同じエラーフォーマットで「HTML は取得できたが本文を抽出できなかった」と表示して終了する。

## STEP 9: JS 依存サイトの検出

`CONVERTED` のバイト数が 1024 未満の場合:

```
⚠️ [JS-DEPENDENT] 取得したコンテンツが非常に少量 (X バイト) です。
   このサイトはJavaScriptで動的にコンテンツを生成している可能性があります。
   curlは静的HTMLのみ取得するため、SPAや動的サイトでは内容が取得できません。
   Omniroute 環境なら --direct を外して再実行すると改善する場合があります。
```

## STEP 10: キャッシュ書き込みとサイズチェック

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

## STEP 11: 出力

以下のフォーマットで出力する:

```
# ページ内容: <URL>
取得日時: <date -u +"%Y-%m-%dT%H:%M:%SZ">
取得経路: <TOOL_USED>
タイトル: <PAGE_TITLE>          ← 取得できた場合のみ
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
