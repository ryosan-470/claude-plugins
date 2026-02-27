#!/usr/bin/env -S uv run
# /// script
# dependencies = ["notebooklm-mcp-cli"]
# ///
"""
sync.py - Confluence to NotebookLM 差分同期ヘルパースクリプト

LLM が Confluence ページを取得した後、(決定論的な処理差分計算、NotebookLM 操作、
メタデータ管理)をすべて担当する。

使い方:
  uv run sync.py plan <notebook_name>
  uv run sync.py sync <notebook_name> --workdir <workdir>
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nlm-confluence-sync"
CONFIG_FILE = CONFIG_DIR / "config.json"
TMP_BASE = Path("/tmp")


def error_exit(message: str, hint: str = "", code: int = 1):
    print(json.dumps({"status": "error", "error": message, "hint": hint}, ensure_ascii=False))
    sys.exit(code)


def load_notebooklm_client():
    from notebooklm_tools import NotebookLMClient
    from notebooklm_tools.core import load_cached_tokens

    tokens = load_cached_tokens()
    if tokens is None:
        error_exit(
            "NotebookLM の認証トークンが見つかりません",
            "notebooklm-mcp auth login を実行してログインしてください",
        )
    return NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id,
    )


def resolve_notebook_id(client, notebook_name: str) -> str:
    notebooks = client.list_notebooks()
    # Pydantic モデルの属性アクセスと dict アクセスの両方を試みる
    for nb in notebooks:
        title = nb.title if hasattr(nb, "title") else nb.get("title", "")
        if title == notebook_name:
            return nb.id if hasattr(nb, "id") else nb["id"]
    available = [
        (nb.title if hasattr(nb, "title") else nb.get("title", ""))
        for nb in notebooks
    ]
    error_exit(
        f'NotebookLM に "{notebook_name}" という名前のノートブックが見つかりません',
        f"利用可能なノートブック: {available}",
    )


def load_metadata(notebook_id: str) -> dict:
    metadata_file = CONFIG_DIR / f"{notebook_id}.json"
    if metadata_file.exists():
        try:
            return json.loads(metadata_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"version": "1", "pages": {}}


def save_metadata(metadata: dict, notebook_id: str, notebook_name: str, now: str):
    metadata["version"] = "1"
    metadata["notebook_id"] = notebook_id
    metadata["notebook_name"] = notebook_name
    metadata["last_synced_at"] = now
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    metadata_file = CONFIG_DIR / f"{notebook_id}.json"
    metadata_file.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_plan(notebook_name: str):
    # 1. 設定ファイルの読み込み
    if not CONFIG_FILE.exists():
        error_exit(
            "設定ファイルが見つかりません",
            (
                f"mkdir -p {CONFIG_DIR} を実行し、{CONFIG_FILE} を作成してください。\n"
                '{\n  "version": "1",\n  "notebooks": {\n'
                '    "<ノートブック名>": {\n      "confluence": {\n'
                '        "cloud_id": "<Cloud ID>",\n'
                '        "sources": [{"type": "pages", "page_ids": ["<page_id>"]}]\n'
                "      }\n    }\n  }\n}"
            ),
        )

    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        error_exit(f"設定ファイルのパースに失敗しました: {e}")

    notebooks_config = config.get("notebooks", {})
    if notebook_name not in notebooks_config:
        available = list(notebooks_config.keys())
        error_exit(
            f'ノートブック "{notebook_name}" の設定が見つかりません',
            f"~/.config/nlm-confluence-sync/config.json に追加してください。"
            f"現在の設定: {available}",
        )

    nb_config = notebooks_config[notebook_name]
    confluence_config = nb_config.get("confluence", {})
    cloud_id = confluence_config.get("cloud_id", "")
    sources = confluence_config.get("sources", [])

    # 2. NotebookLM ノートブック ID の解決
    client = load_notebooklm_client()
    notebook_id = resolve_notebook_id(client, notebook_name)

    # 3. メタデータの読み込み
    metadata = load_metadata(notebook_id)
    known_pages = metadata.get("pages", {})

    # 4. workdir の作成
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    workdir = TMP_BASE / f"nlm-sync-{run_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "pages").mkdir(exist_ok=True)

    # 5. マニフェスト出力
    print(
        json.dumps(
            {
                "status": "ok",
                "notebook_id": notebook_id,
                "notebook_name": notebook_name,
                "cloud_id": cloud_id,
                "workdir": str(workdir),
                "sources": sources,
                "known_pages": known_pages,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_sync(notebook_name: str, workdir_path: str):
    workdir = Path(workdir_path)

    # 1. 設定ファイルの読み込み
    if not CONFIG_FILE.exists():
        error_exit("設定ファイルが見つかりません")
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    notebooks_config = config.get("notebooks", {})
    if notebook_name not in notebooks_config:
        error_exit(f'ノートブック "{notebook_name}" の設定が見つかりません')

    # 2. LLM が取得したページを読み込む
    pages_dir = workdir / "pages"
    if not pages_dir.exists():
        error_exit(f"workdir が見つかりません: {workdir}")

    current_pages: dict[str, dict] = {}
    for page_file in pages_dir.glob("*.json"):
        try:
            page_data = json.loads(page_file.read_text(encoding="utf-8"))
            page_id = page_data["page_id"]
            current_pages[page_id] = page_data
        except (json.JSONDecodeError, KeyError):
            continue

    # 3. NotebookLM クライアントの初期化とノートブック ID 解決
    client = load_notebooklm_client()
    notebook_id = resolve_notebook_id(client, notebook_name)

    # 4. メタデータの読み込み
    metadata = load_metadata(notebook_id)
    known_pages: dict[str, dict] = metadata.get("pages", {})

    # 5. 差分計算
    known_ids = set(known_pages.keys())
    current_ids = set(current_pages.keys())

    to_delete = known_ids - current_ids
    to_add = current_ids - known_ids
    to_update = {
        pid
        for pid in known_ids & current_ids
        if current_pages[pid].get("version", 0)
        != known_pages[pid].get("page_version", -1)
    }
    unchanged_count = len((known_ids & current_ids) - to_update)

    errors = []
    added = updated = deleted = 0
    now = datetime.now(timezone.utc).isoformat()

    # 6. 削除
    for page_id in to_delete:
        source_id = known_pages[page_id].get("source_id")
        if source_id:
            try:
                client.delete_source(source_id)
                del metadata["pages"][page_id]
                save_metadata(metadata, notebook_id, notebook_name, now)
                deleted += 1
            except Exception as e:
                errors.append({"page_id": page_id, "action": "delete", "error": str(e)})

    # 7. 更新・追加
    for page_id in list(to_update) + list(to_add):
        page_data = current_pages[page_id]
        title = page_data["title"]
        content = page_data["content_markdown"]

        # 更新の場合は古いソースを削除してから再追加する
        if page_id in to_update:
            old_source_id = known_pages[page_id].get("source_id")
            if old_source_id:
                try:
                    client.delete_source(old_source_id)
                except Exception as e:
                    errors.append(
                        {"page_id": page_id, "title": title, "action": "delete_before_update", "error": str(e)}
                    )
                    continue  # 削除失敗時は重複防止のためスキップ

        # ファイル名に [CONF:<page_id>] プレフィックスを付けてタイトルとして認識させる
        safe_title = title.replace("/", "-").replace("\\", "-").replace("\0", "")
        tmp_file = workdir / f"[CONF:{page_id}] {safe_title}.md"
        tmp_file.write_text(content, encoding="utf-8")

        try:
            result = client.add_file(notebook_id, str(tmp_file))
            # Pydantic モデルと dict の両方に対応
            source_id = (
                result.id if hasattr(result, "id") else result.get("id", str(result))
            )

            metadata["pages"][page_id] = {
                "source_id": source_id,
                "page_version": page_data.get("version", 0),
                "page_title": title,
                "synced_at": now,
            }
            save_metadata(metadata, notebook_id, notebook_name, now)

            if page_id in to_update:
                updated += 1
            else:
                added += 1
        except Exception as e:
            errors.append(
                {"page_id": page_id, "title": title, "action": "add", "error": str(e)}
            )
        finally:
            tmp_file.unlink(missing_ok=True)

    # 8. workdir のクリーンアップ
    shutil.rmtree(workdir, ignore_errors=True)

    # 9. サマリー出力
    print(
        json.dumps(
            {
                "status": "ok",
                "added": added,
                "updated": updated,
                "deleted": deleted,
                "unchanged": unchanged_count,
                "total_managed": len(metadata.get("pages", {})),
                "errors": errors,
                "synced_at": now,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Confluence to NotebookLM 差分同期ヘルパー"
    )
    subparsers = parser.add_subparsers(dest="command")

    plan_parser = subparsers.add_parser("plan", help="同期計画を作成し、fetch マニフェストを出力する")
    plan_parser.add_argument("notebook_name", help="NotebookLM ノートブック名")

    sync_parser = subparsers.add_parser("sync", help="取得済みページを NotebookLM に同期する")
    sync_parser.add_argument("notebook_name", help="NotebookLM ノートブック名")
    sync_parser.add_argument("--workdir", required=True, help="LLM が pages/*.json を保存した workdir")

    args = parser.parse_args()

    if args.command == "plan":
        cmd_plan(args.notebook_name)
    elif args.command == "sync":
        cmd_sync(args.notebook_name, args.workdir)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
