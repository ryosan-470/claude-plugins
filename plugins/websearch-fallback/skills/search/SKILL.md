---
description: Omniroute の /api/v1/search で Web 検索し、URL / タイトル / スニペットを返す。標準 WebSearch がプロキシの streaming 経路で検索結果を返さない環境向け。
argument-hint: <query> [--max N] [--type web|news|x|finance] [--provider ID]
allowed-tools: Bash
---

# websearch-fallback:search — Omniroute の検索 API を使う

Claude Code 標準の `WebSearch` は常にストリーミングで API を叩く。Anthropic 互換プロキシ (Omniroute) が streaming 経路で `web_search` サーバーツールを実行しない場合、検索結果 0 件のままモデルの前置きテキストだけが返り、成功したように見える。このスキルは Omniroute の専用 API `POST /api/v1/search` を直接叩き、実際の検索結果を取得する。

**結果 0 件を成功として扱わない。** `.results` が空で `.answer` もない場合、または HTTP エラーの場合は失敗として報告し、「検索した」というテキストで埋めない。`.answer` だけがある場合は回答として表示する。

## STEP 1: 引数の解析

引数全体を `$ARGUMENTS` として受け取る。

```bash
ARGUMENTS="$ARGUMENTS"  # スキルランタイムが注入
```

トークンに分解して解析する:

| 引数 | 既定値 | 内容 |
| --- | --- | --- |
| `--max N` | `5` | 最大件数。1〜100 に丸める |
| `--type T` | `web` | `web` / `news` / `x` / `finance` |
| `--provider ID` | なし | 検索プロバイダー ID。省略時は Omniroute の自動選択 |
| それ以外 | - | 検索クエリ (複数トークンはスペースで連結) |

`--max` は数値以外を `5` にフォールバックし、1〜100 に丸める:

```bash
MAX_RESULTS=5
SEARCH_TYPE="web"
PROVIDER_ID=""
QUERY_PARTS=()
# トークンを順に走査し、上記を埋める。QUERY_PARTS はスペースで連結して QUERY にする。

case "$MAX_RESULTS" in ''|*[!0-9]*) MAX_RESULTS=5 ;; esac
if [ "$MAX_RESULTS" -lt 1 ]; then MAX_RESULTS=1; fi
if [ "$MAX_RESULTS" -gt 100 ]; then MAX_RESULTS=100; fi
```

クエリが空の場合は以下を表示して終了する:

```
エラー: 検索クエリを指定してください。
使用方法: /websearch-fallback:search <query> [--max N] [--type web|news|x|finance] [--provider ID]
例: /websearch-fallback:search Claude Code changelog --max 5
```

## STEP 2: Omniroute の判定

```bash
BASE_URL="${WEBSEARCH_BASE_URL:-${ANTHROPIC_BASE_URL:-}}"
BASE_URL="${BASE_URL%/}"

if [ -z "$BASE_URL" ]; then
  echo "エラー: ANTHROPIC_BASE_URL が未設定です。このスキルは Omniroute 専用です。"
  echo "プロキシを使っていない場合は標準の WebSearch を使用してください。"
  exit 1
fi

AUTH_HEADER=()
if [ -n "${OMNIROUTE_API_KEY:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${OMNIROUTE_API_KEY}")
elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${ANTHROPIC_AUTH_TOKEN}")
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "エラー: jq が必要です (例: brew install jq)。"
  exit 1
fi

PROBE=$(mktemp /tmp/wfs-providers-XXXXXX)
PROBE_CODE=$(curl -sS --max-time 5 -o "$PROBE" -w '%{http_code}' \
  "${AUTH_HEADER[@]}" "$BASE_URL/api/v1/search" 2>/dev/null)

if [ "$PROBE_CODE" != "200" ] || \
   ! jq -e '.object == "list" and ([.data[]? | select(.object == "search_provider")] | length > 0)' \
     "$PROBE" >/dev/null 2>&1; then
  echo "エラー: $BASE_URL は Omniroute の検索 API を提供していません (HTTP $PROBE_CODE)。"
  echo "ANTHROPIC_BASE_URL / WEBSEARCH_BASE_URL を確認するか、標準の WebSearch を使用してください。"
  rm -f "$PROBE"
  exit 1
fi
```

`PROBE` は STEP 3 のプロバイダー確認でも使うため、ここでは削除しない。

`WEBSEARCH_BASE_URL` / `ANTHROPIC_BASE_URL` はホストのルートを指定する (`.../v1` などのパスを含めない)。API パスは自動で `/api/v1/...` を付与する。

## STEP 3: プロバイダーの確認 (--provider 指定時のみ)

`PROVIDER_ID` が指定されている場合、`$PROBE` の `.data[].id` に含まれるか確認する。含まれない場合は利用可能な ID を列挙して終了する:

```
エラー: 不明な検索プロバイダーです: <PROVIDER_ID>
利用可能なプロバイダー:
  serper-search, brave-search, ...
```

```bash
if [ -n "$PROVIDER_ID" ]; then
  PROVIDERS=$(jq -r '[.data[].id] | join(", ")' "$PROBE")
  if ! jq -e --arg p "$PROVIDER_ID" '[.data[].id] | index($p) != null' "$PROBE" >/dev/null; then
    echo "エラー: 不明な検索プロバイダーです: $PROVIDER_ID"
    echo "利用可能なプロバイダー: $PROVIDERS"
    rm -f "$PROBE"
    exit 1
  fi
fi
rm -f "$PROBE"
```

## STEP 4: 検索リクエスト

```bash
BODY=$(jq -n \
  --arg q "$QUERY" \
  --argjson max "$MAX_RESULTS" \
  --arg type "$SEARCH_TYPE" \
  --arg provider "$PROVIDER_ID" \
  '{query: $q, max_results: $max, search_type: $type}
   + (if $provider == "" then {} else {provider: $provider} end)')

TMP=$(mktemp /tmp/wfs-results-XXXXXX)
HTTP_CODE=$(curl -sS --max-time 90 -o "$TMP" -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/search" \
  -H 'content-type: application/json' \
  "${AUTH_HEADER[@]}" \
  -d "$BODY" 2>/tmp/wfs-curl-err.txt)
```

注意:

- レスポンスは数百 KB〜数 MB になることがある (`.results[].content` / `.snippet` が長い)。**必ずファイルに落として jq で必要な項目だけを取り出す**。生のレスポンスをそのまま表示しない
- `model` と `provider` は同時指定できない。このスキルは `provider` のみ使う
- `search_type: x` は `xquik-search` (`xquik` / `xquik_search` も可) を明示した場合のみ有効

## STEP 5: 結果の検証

```bash
if [ "$HTTP_CODE" != "200" ]; then
  ERROR_MSG=$(jq -r '.error.message // empty' "$TMP" 2>/dev/null)
  ERROR_CODE=$(jq -r '.error.code // empty' "$TMP" 2>/dev/null)
  echo "❌ 検索 API が失敗しました (HTTP $HTTP_CODE): ${ERROR_MSG:-$(cat /tmp/wfs-curl-err.txt 2>/dev/null)}"
  if [ -n "$ERROR_CODE" ]; then echo "   code: $ERROR_CODE"; fi
  jq -r '.errors[]? | "   - \(.provider // "-") [\(.code // "-")]: \(.message // "")"' "$TMP" 2>/dev/null
  rm -f "$TMP"
  exit 1
fi

RESULT_COUNT=$(jq '.results | length' "$TMP" 2>/dev/null || echo 0)
ANSWER_PRESENT=false
if jq -e '.answer != null and .answer != "" and .answer != {}' "$TMP" >/dev/null 2>&1; then
  ANSWER_PRESENT=true
fi
if { [ "$RESULT_COUNT" = "0" ] || [ -z "$RESULT_COUNT" ]; } && [ "$ANSWER_PRESENT" != "true" ]; then
  PROVIDER=$(jq -r '.provider // "unknown"' "$TMP")
  echo "⚠️ 検索結果は 0 件でした。"
  echo "   provider: $PROVIDER / query: $QUERY"
  jq -r '.errors[]? | "   - \(.provider // "-") [\(.code // "-")]: \(.message // "")"' "$TMP" 2>/dev/null
  echo "   クエリを言い換えるか、--provider を変えて再実行してください。"
  rm -f "$TMP"
  exit 1
fi
```

## STEP 6: 出力

```bash
PROVIDER=$(jq -r '.provider // "unknown"' "$TMP")
CACHED=$(jq -r '.cached // false' "$TMP")
```

以下のフォーマットで出力する。スニペットは **先に切り詰めてから** 空白を正規化する (数 MB のスニペットに対して `gsub` をかけると極端に遅くなる):

```bash
jq -r --arg q "$QUERY" --arg p "$PROVIDER" --arg t "$SEARCH_TYPE" --arg c "$CACHED" --argjson n "$RESULT_COUNT" '
  "# 検索結果: \($q)",
  "プロバイダー: \($p) / 種別: \($t) / 件数: \($n) / キャッシュ: \($c)",
  "",
  (.results | to_entries[] |
    "\(.key + 1). \(.value.title // "(no title)")",
    "   \(.value.url)",
    (if ((.value.snippet // "") | length) > 0
     then "   \((.value.snippet // "")[0:400] | gsub("\\s+"; " ") | .[0:200])"
     else empty end),
    "")
' "$TMP"
```

`.answer` が空でない場合は末尾に要約セクションを追加する (プロバイダーが生成した回答であり、ソース URL ではない点を明示する)。`.answer` は文字列のほか object の場合もあるため、object は JSON 文字列化して先頭 1000 文字を出す:

```
---
## プロバイダーによる回答 (参考)
<answer の先頭 1000 文字>
```

```bash
ANSWER=$(jq -r 'if (.answer | type) == "object" then (.answer | tostring) elif (.answer | type) == "string" then .answer else empty end' "$TMP")
if [ -n "$ANSWER" ]; then
  printf '%s\n' '---' '## プロバイダーによる回答 (参考)' "${ANSWER:0:1000}"
fi
rm -f "$TMP"
```

出力後、取得した URL を根拠として回答を組み立てる。**`web_search_tool_result` に相当する実データは `.results` だけ**であり、モデルの記憶や推測で補完しない。
