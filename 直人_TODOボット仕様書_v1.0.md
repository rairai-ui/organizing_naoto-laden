# 直人さん専用 TODOボット
## パーソナルナレッジ＆タスク管理Webアプリ 機能仕様書 v1.0 | Antigravity 開発用

---

## 1. プロジェクト概要

### 1-1. 目的

直人さんが日々の作業・TODO・完了報告・ドキュメントをインプットし続けることで、チャットで「あの件どうだったっけ？」「今週のTODOは？」と聞けば即座に答えてくれる個人専用AIボットを構築する。

### 1-2. KPI（成功基準）

- 音声・ファイル・テキスト・完了報告のインプットが1画面から完結する
- インプットした内容がチャットで検索・回答できる（RAG）
- TODO管理（登録・完了・期限・優先度）が一元管理できる
- Renderにデプロイして、どこからでもアクセスできる

### 1-3. 技術スタック

| レイヤー | 技術 | 役割 |
|---|---|---|
| バックエンド | Python / FastAPI | APIサーバー（既存コードを拡張） |
| AI処理 | Gemini API (gemini-flash-latest) | 文字起こし・TODO抽出・要約・埋め込み・RAG回答 |
| 構造DB | SQLite | TODO・メモ・完了報告のテキスト永続化 |
| ベクトルDB | ChromaDB | 意味検索用ベクトルインデックス |
| フロントエンド | HTML / Vanilla JS | 既存index.htmlを3画面に拡張 |
| デプロイ | Render（Web Service） | パブリックURL、永続ディスク設定 |

---

## 2. ファイル構成

```
naoto-todo-bot/
├── main.py                 # FastAPI エントリーポイント（既存を拡張）
├── db.py                   # SQLite 初期化・CRUD
├── vector_store.py         # ChromaDB 操作
├── gemini_service.py       # Gemini API ラッパー（文字起こし・要約・埋め込み・RAG）
├── models.py               # Pydantic モデル定義
├── requirements.txt        # 依存パッケージ
├── render.yaml             # Render デプロイ設定
├── .env.example            # 環境変数サンプル
├── .antigravityignore      # GEMINI_API_KEY 等を除外
└── static/
    └── index.html          # 3画面SPA（ホーム・TODO一覧・チャット）
```

---

## 3. データモデル（SQLite）

### 3-1. memories テーブル

あらゆるインプット（音声・ファイル・テキスト・完了報告）を統一的に蓄積するテーブル。

| カラム | 型 | 説明 |
|---|---|---|
| id | TEXT PRIMARY KEY | UUID v4 |
| type | TEXT NOT NULL | voice / file / text / completion |
| content | TEXT NOT NULL | 文字起こし・要約・テキスト本文 |
| summary | TEXT | Geminiによる要約（任意） |
| source_filename | TEXT | 元ファイル名（音声・PDFの場合） |
| chroma_id | TEXT | ChromaDB上の対応ベクトルID |
| created_at | DATETIME DEFAULT CURRENT_TIMESTAMP | 登録日時 |

### 3-2. todos テーブル

| カラム | 型 | 説明 |
|---|---|---|
| id | TEXT PRIMARY KEY | UUID v4 |
| title | TEXT NOT NULL | タスクタイトル |
| description | TEXT | 詳細・メモ |
| status | TEXT DEFAULT 'pending' | pending / in_progress / done |
| priority | TEXT DEFAULT 'medium' | low / medium / high |
| due_date | DATE | 期限（任意） |
| memory_id | TEXT | 抽出元の memories.id（外部キー相当） |
| completed_at | DATETIME | 完了日時 |
| completion_note | TEXT | 完了時のメモ（→ memoriesに追加蓄積） |
| created_at | DATETIME DEFAULT CURRENT_TIMESTAMP | 登録日時 |

---

## 4. API エンドポイント仕様

### 4-1. インプット系

#### POST /api/input/voice

音声ファイル（+任意PDF）を受け取り、文字起こし→TODO抽出→要約→ベクトル化→蓄積を一気通貫で行う。

| 項目 | 内容 |
|---|---|
| Content-Type | multipart/form-data |
| パラメータ | file: UploadFile（必須）、pdf: UploadFile（任意） |
| 処理フロー | ①Geminiで文字起こし → ②TODO抽出（JSON）→ ③要約 → ④memories保存 → ⑤ChromaDB保存 → ⑥todos保存 |
| レスポンス | { memory_id, transcription, summary, todos_created: [] } |

#### POST /api/input/text

テキストを直接インプット。Geminiでそのままの内容を要約・TODO抽出・ベクトル化して保存。

| 項目 | 内容 |
|---|---|
| Content-Type | application/json |
| Body | { "text": "string" } |
| レスポンス | { memory_id, summary, todos_created: [] } |

### 4-2. TODO管理系

#### GET /api/todos

| パラメータ | 型 | 説明 |
|---|---|---|
| status | string（任意） | pending / in_progress / done でフィルタ |
| priority | string（任意） | low / medium / high でフィルタ |

#### PATCH /api/todos/{id}/complete

タスクを完了にする。completion_noteを受け取り、memoriesテーブルにtype='completion'で追加登録し、ChromaDBにもベクトル化して保存する（完了報告も検索可能にする）。

| 項目 | 内容 |
|---|---|
| Body | { "completion_note": "string（任意）" } |
| 処理 | todos.status='done'に更新 → memoriesにtype=completionで追加 → ChromaDBに保存 |
| レスポンス | { todo, memory_id } |

#### その他TODOエンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| POST | /api/todos | 手動でTODO登録 |
| PATCH | /api/todos/{id} | タイトル・期限・優先度・ステータス更新 |
| DELETE | /api/todos/{id} | 削除 |

### 4-3. チャット（RAG）系

#### POST /api/chat

質問文をChromaDBでベクトル検索し、上位5件の関連memoriesをコンテキストとしてGeminiに渡して回答を生成する。

| 項目 | 内容 |
|---|---|
| Body | { "message": "string", "history": [ {role, content} ] } |
| 処理 | ①質問をGemini embed → ②ChromaDB検索（top5）→ ③該当memoriesをコンテキスト化 → ④Gemini回答生成 |
| レスポンス | { answer, sources: [ {memory_id, type, summary, created_at} ] } |
| 履歴 | フロントから最大10ターン分のhistoryを毎回送信。バックエンドは永続化不要 |

---

## 5. Gemini プロンプト設計

### 5-1. TODO抽出プロンプト

```
SYSTEM: あなたはタスク管理AIです。
USER: 以下のテキストからTODOタスクを抽出し、JSONのみで返してください。
      タスクがなければ空配列を返してください。
      フォーマット: [{"title":"...", "priority":"high/medium/low", "due_date":"YYYY-MM-DD or null"}]
      テキスト: {transcription}
```

### 5-2. RAG回答プロンプト

```
SYSTEM: あなたは直人さんの個人アシスタントAIです。
        以下の「過去のメモ・作業記録」を参照して質問に答えてください。
        記録にない内容は「記録にありません」と答えてください。
USER: [過去のメモ・作業記録]
      {context_chunks}

      [質問]
      {user_message}
```

---

## 6. フロントエンド（index.html）

既存のindex.htmlをベースに、ナビゲーションバー付き3画面SPAに拡張する。

### 6-1. 画面構成

| 画面 | URL hash | 主な要素 |
|---|---|---|
| ホーム（インプット） | #home | 録音ボタン・音声ファイルUP・PDF追加・テキスト入力・実行ボタン・結果プレビュー |
| TODO一覧 | #todos | フィルタ（全・未完了・完了）・TODOカード（優先度バッジ・期限）・完了ボタン（メモ入力）・手動追加 |
| チャット | #chat | チャット履歴エリア・入力欄・送信ボタン・ソース表示（参照したメモ） |

### 6-2. 完了報告フロー（重要）

1. TODOカードの「完了」ボタンを押す
2. モーダルが開き「どう終わった？」テキストエリアが表示される（任意入力）
3. 「完了を記録」ボタン押下 → PATCH /api/todos/{id}/complete を呼ぶ
4. バックエンドで completion_note を memoriesに保存 → ChromaDBにベクトル化
5. チャットで「あの件どう終わった？」と聞けば参照できる

---

## 7. Render デプロイ設定

### 7-1. render.yaml

```yaml
services:
  - type: web
    name: naoto-todo-bot
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    disk:
      name: data
      mountPath: /data
      sizeGB: 1
    envVars:
      - key: GEMINI_API_KEY
        sync: false
      - key: DATA_DIR
        value: /data
```

### 7-2. データパス（環境変数 DATA_DIR）

Renderの永続ディスクに SQLite と ChromaDB を配置する。

- SQLite: {DATA_DIR}/naoto.db
- ChromaDB: {DATA_DIR}/chroma/
- ローカル開発時は DATA_DIR=. で動作

### 7-3. .antigravityignore

```
.env
*.db
chroma/
*.mp3 *.wav *.m4a *.ogg *.flac *.webm *.mp4
```

---

## 8. 実装ロードマップ

| フェーズ | タスク | 優先度 |
|---|---|---|
| Phase 1 | db.py: memoriesテーブル・todosテーブル作成・CRUD実装 | 高 |
| Phase 1 | vector_store.py: ChromaDB初期化・add/search実装 | 高 |
| Phase 1 | gemini_service.py: 文字起こし・TODO抽出・要約・埋め込み・RAG回答 | 高 |
| Phase 2 | main.py: POST /api/input/voice 実装（既存/api/transcribeを拡張） | 高 |
| Phase 2 | main.py: POST /api/input/text 実装 | 高 |
| Phase 2 | main.py: GET/POST/PATCH/DELETE /api/todos 実装 | 高 |
| Phase 2 | main.py: PATCH /api/todos/{id}/complete 実装（完了報告→memories蓄積） | 高 |
| Phase 3 | main.py: POST /api/chat 実装（RAG回答生成） | 高 |
| Phase 4 | index.html: 3画面SPA（ホーム・TODO一覧・チャット） | 高 |
| Phase 5 | render.yaml作成・Renderデプロイ・動作確認 | 高 |

---

## 9. 環境変数

| 変数名 | 説明 | 例 |
|---|---|---|
| GEMINI_API_KEY | Gemini APIキー | AIza... |
| DATA_DIR | DB・ChromaDBの保存先 | ./（ローカル）/ /data（Render） |

---

## 10. 備考・設計決定事項

- Gemini Files APIは48時間でファイルが削除される仕様のため、テキスト化したデータはSQLiteとChromaDBに永続化する
- チャット履歴の永続化はフェーズ1では不要。フロント側で会話履歴を保持し、毎回APIに送信する
- 認証はフェーズ1では不要。直人さん1人の個人ツールとして設計
- 将来的にNotionやSlackとの連携を追加したい場合はmemories.typeに新種別を追加するだけで拡張できる
