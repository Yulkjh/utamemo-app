# 🎵 UTAMEMO 独自LLM構築ロードマップ

## 概要

現在UTAMEMOでは、Google Gemini APIを使用して以下の機能を実現しています：

1. **OCR（画像からテキスト抽出）**
2. **歌詞生成（テキストから学習用歌詞を作成）**
3. **ひらがな変換（漢字→ひらがな、発音調整）**

この文書では、これらを**独自のLLM（大規模言語モデル）**に置き換える方法を説明します。

---

## 📊 現在のシステム構成

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   ユーザー入力    │────▶│   Gemini API    │────▶│    歌詞出力      │
│  （画像/テキスト） │     │  （外部サービス）  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌─────────────────┐
                        │   Mureka API    │
                        │   （音楽生成）    │
                        └─────────────────┘
```

### 現在の処理フロー（ai_services.py）

```python
# 1. OCR処理
class GeminiOCR:
    def extract_text_from_image(self, image_file):
        response = self.model.generate_content([prompt, img])
        return response.text

# 2. 歌詞生成
class GeminiLyricsGenerator:
    def generate_lyrics(self, extracted_text, genre, language_mode):
        prompt = self._get_japanese_prompt(extracted_text, genre)
        response = self.model.generate_content(prompt)
        return response.text

# 3. ひらがな変換
def convert_lyrics_to_hiragana_with_context(lyrics):
    prompt = f"以下の歌詞をひらがなに変換..."
    response = model.generate_content(prompt)
    return response.text
```

---

## 🎯 独自LLMを作る3つのアプローチ

### アプローチ1: ファインチューニング（推奨・現実的）

既存のオープンソースLLMを**歌詞生成タスク専用にチューニング**する方法。

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  ベースモデル     │────▶│  ファインチューニング │────▶│  UTAMEMO専用モデル │
│ （Llama, Mistral）│     │  （歌詞データで学習） │     │                   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

#### メリット
- 比較的少ないデータ（数千〜数万件）で実現可能
- 学習コストが低い（数時間〜数日）
- 高品質なベースモデルの能力を活用できる

#### 必要なもの
- **ベースモデル**: Llama 3, Mistral, Qwen など
- **学習データ**: 入力テキスト → 歌詞 のペアデータ
- **GPU**: RTX 4090（24GB VRAM）以上推奨

---

### アプローチ2: RAG（Retrieval-Augmented Generation）

歌詞のテンプレートやパターンを**データベースから検索して参照**する方法。

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   ユーザー入力    │────▶│   検索エンジン     │────▶│   関連歌詞取得    │
└─────────────────┘     │  （Vector DB）    │     └────────┬────────┘
                        └─────────────────┘              │
                                                         ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │    最終出力      │◀────│   小規模LLM      │
                        └─────────────────┘     │ （参照して生成）   │
                                                └─────────────────┘
```

#### メリット
- 学習不要、すぐに始められる
- 新しいパターンを追加するのが簡単
- モデルサイズを小さく保てる

---

### アプローチ3: フルスクラッチ学習（上級者向け）

完全にゼロからモデルを構築する方法。

#### 必要リソース
- 大量のデータ（数十億トークン）
- 大規模GPU（A100 × 複数台）
- 数ヶ月の学習時間

> ⚠️ 現実的には企業レベルのリソースが必要。個人開発ではアプローチ1がおすすめ。

---

## 🛠️ 実装ステップ（アプローチ1: ファインチューニング）

### Step 1: データ収集・作成

UTAMEMOで生成した歌詞データを収集します。

```python
# データ形式の例（JSONL）
{
    "input": "縄文時代は紀元前14000年頃から...",
    "output": "[Verse 1]\nじょうもん じだい の はじまり\nいちまんよんせんねん まえ\n..."
}
```

#### データ収集スクリプト例

```python
# scripts/collect_training_data.py
import json
from songs.models import Song, Lyrics

def export_training_data():
    """UTAMEMOの歌詞データを学習用にエクスポート"""
    training_data = []
    
    for song in Song.objects.filter(is_public=True):
        if hasattr(song, 'lyrics') and song.lyrics:
            data = {
                "instruction": "以下のテキストから学習用の歌詞を生成してください。",
                "input": song.lyrics.original_text or "",  # 元のテキスト
                "output": song.lyrics.content,  # 生成された歌詞
                "genre": song.genre,
                "language_mode": "japanese"
            }
            training_data.append(data)
    
    with open('training_data.jsonl', 'w', encoding='utf-8') as f:
        for item in training_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Exported {len(training_data)} samples")

if __name__ == "__main__":
    export_training_data()
```

### Step 2: ベースモデルの選択

| モデル | パラメータ数 | 日本語対応 | 推奨GPU |
|-------|-----------|----------|--------|
| **Llama 3.1 8B** | 80億 | ◯ | RTX 4090 (24GB) |
| **Mistral 7B** | 70億 | △ | RTX 4090 (24GB) |
| **Qwen2 7B** | 70億 | ◎ | RTX 4090 (24GB) |
| **ELYZA-japanese-Llama-2-7b** | 70億 | ◎ | RTX 4090 (24GB) |

> 💡 日本語歌詞生成には **Qwen2** または **ELYZA** がおすすめ

### Step 3: ファインチューニング実行

```python
# scripts/finetune_lyrics_model.py
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer
import torch

# 1. モデルとトークナイザーの読み込み
model_name = "Qwen/Qwen2-7B-Instruct"
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.bfloat16,
    device_map="auto"
)
tokenizer = AutoTokenizer.from_pretrained(model_name)

# 2. LoRA設定（効率的なファインチューニング）
lora_config = LoraConfig(
    r=16,                      # LoRAのランク
    lora_alpha=32,             # スケーリング係数
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora_config)

# 3. トレーニング設定
training_args = TrainingArguments(
    output_dir="./utamemo-lyrics-model",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    warmup_steps=100,
    logging_steps=10,
    save_steps=500,
    fp16=True,
)

# 4. データセット読み込み
from datasets import load_dataset
dataset = load_dataset('json', data_files='training_data.jsonl')

# 5. トレーニング実行
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset['train'],
    args=training_args,
    tokenizer=tokenizer,
    max_seq_length=2048,
)

trainer.train()

# 6. モデル保存
model.save_pretrained("./utamemo-lyrics-model-final")
tokenizer.save_pretrained("./utamemo-lyrics-model-final")
```

### Step 4: UTAMEMOへの統合

```python
# songs/ai_services.py に追加

class CustomLyricsGenerator:
    """独自ファインチューニングモデルによる歌詞生成"""
    
    def __init__(self):
        self.model_path = "./utamemo-lyrics-model-final"
        self.model = None
        self.tokenizer = None
        self._load_model()
    
    def _load_model(self):
        """モデルを遅延読み込み"""
        if self.model is None:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.float16,
                device_map="auto"
            )
    
    def generate_lyrics(self, extracted_text, genre="pop", language_mode="japanese"):
        """歌詞を生成"""
        self._load_model()
        
        prompt = f"""### 指示
以下のテキストから{genre}ジャンルの学習用歌詞を生成してください。

### 入力テキスト
{extracted_text}

### 歌詞
"""
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=1024,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            pad_token_id=self.tokenizer.eos_token_id
        )
        
        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # プロンプト部分を除去して歌詞だけを返す
        lyrics = generated_text.split("### 歌詞")[-1].strip()
        return lyrics


# 切り替え可能な設計
def get_lyrics_generator(use_custom_model=False):
    """歌詞生成器を取得（切り替え可能）"""
    if use_custom_model:
        return CustomLyricsGenerator()
    else:
        return GeminiLyricsGenerator()
```

---

## 📈 学習データを増やす戦略

### 1. ユーザー生成データの活用

```python
# models.py に学習データ収集用フィールドを追加
class Lyrics(models.Model):
    # 既存フィールド...
    
    # 学習データとして使用可能かのフラグ
    can_use_for_training = models.BooleanField(default=False)
    
    # ユーザーによる品質評価
    quality_rating = models.IntegerField(null=True, blank=True)  # 1-5
```

### 2. データ拡張（Data Augmentation）

```python
def augment_lyrics_data(original_data):
    """学習データを拡張"""
    augmented = []
    
    for item in original_data:
        # オリジナル
        augmented.append(item)
        
        # ジャンル変更版
        for genre in ["pop", "rock", "ballad", "edm"]:
            augmented.append({
                **item,
                "genre": genre,
                "instruction": f"以下のテキストから{genre}ジャンルの歌詞を生成..."
            })
    
    return augmented
```

### 3. 合成データ生成

Gemini APIを使って、学習用のペアデータを自動生成：

```python
def generate_synthetic_training_data(num_samples=1000):
    """合成学習データを生成"""
    topics = ["歴史", "科学", "数学", "英語", "地理"]
    
    for topic in topics:
        prompt = f"""
        {topic}に関する教科書風の説明文を生成してください。
        その後、その内容を学習用歌詞に変換してください。
        """
        # Geminiで生成 → 学習データとして保存
```

---

## 🖥️ デプロイ構成

### ローカルGPUサーバー構成

```
┌─────────────────────────────────────────────────────────┐
│                    Render (Web Server)                   │
│                    Django Application                    │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP API
                      ▼
┌─────────────────────────────────────────────────────────┐
│              自宅/クラウド GPU Server                     │
│  ┌─────────────────┐  ┌─────────────────┐               │
│  │  FastAPI Server │  │  独自LLMモデル    │               │
│  │  (推論API)       │  │  (GPU上で実行)   │               │
│  └─────────────────┘  └─────────────────┘               │
│                    RTX 4090 / A100                       │
└─────────────────────────────────────────────────────────┘
```

### 推論APIサーバー例

```python
# inference_server.py
from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

app = FastAPI()

# モデルをグローバルに読み込み
model = None
tokenizer = None

@app.on_event("startup")
async def load_model():
    global model, tokenizer
    tokenizer = AutoTokenizer.from_pretrained("./utamemo-lyrics-model-final")
    model = AutoModelForCausalLM.from_pretrained(
        "./utamemo-lyrics-model-final",
        torch_dtype=torch.float16,
        device_map="auto"
    )

class LyricsRequest(BaseModel):
    text: str
    genre: str = "pop"
    language_mode: str = "japanese"

class LyricsResponse(BaseModel):
    lyrics: str
    model_version: str

@app.post("/generate", response_model=LyricsResponse)
async def generate_lyrics(request: LyricsRequest):
    prompt = f"### 指示\n{request.text}\n### 歌詞\n"
    
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(**inputs, max_new_tokens=1024)
    lyrics = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    return LyricsResponse(
        lyrics=lyrics.split("### 歌詞")[-1].strip(),
        model_version="utamemo-v1.0"
    )

# 起動: uvicorn inference_server:app --host 0.0.0.0 --port 8000
```

---

## 💰 コスト比較

| 項目 | Gemini API（現在） | 独自LLM |
|-----|------------------|--------|
| **初期コスト** | $0 | ¥300,000〜（GPU購入） |
| **月額コスト** | 使用量による（$10-100+） | 電気代のみ（¥3,000程度） |
| **レイテンシ** | 1-3秒 | 0.3-1秒（ローカル） |
| **カスタマイズ性** | プロンプトのみ | 完全自由 |
| **データプライバシー** | Google に送信 | 完全ローカル |
| **スケーラビリティ** | 無制限 | GPUの処理能力に依存 |

---

## 🗓️ 推奨ロードマップ

```
Phase 1 (1-2ヶ月): データ収集
├── UTAMEMOの生成データをエクスポート
├── 品質の良いデータを選別（1000件以上目標）
└── データ形式の統一

Phase 2 (1ヶ月): 実験環境構築
├── GPU環境のセットアップ
├── ベースモデルの選定・テスト
└── 小規模データでファインチューニング試行

Phase 3 (2-3ヶ月): 本格学習
├── フルデータでのファインチューニング
├── ハイパーパラメータ調整
└── 評価・改善のイテレーション

Phase 4 (1ヶ月): 統合・デプロイ
├── 推論APIサーバー構築
├── UTAMEMOへの統合
└── A/Bテスト（Gemini vs 独自モデル）

Phase 5 (継続): 改善
├── ユーザーフィードバック収集
├── 継続的なモデル改善
└── 新機能追加（OCR専用モデルなど）
```

---

## 📚 参考リソース

### 学習リソース
- [Hugging Face Transformers ドキュメント](https://huggingface.co/docs/transformers)
- [LoRA: Low-Rank Adaptation 論文](https://arxiv.org/abs/2106.09685)
- [LLM Fine-tuning Guide](https://huggingface.co/docs/trl/sft_trainer)

### おすすめベースモデル
- [Qwen2](https://huggingface.co/Qwen/Qwen2-7B-Instruct) - 日本語性能が高い
- [ELYZA-japanese-Llama-2](https://huggingface.co/elyza/ELYZA-japanese-Llama-2-7b-instruct)
- [Japanese-StableLM](https://huggingface.co/stabilityai/japanese-stablelm-base-gamma-7b)

### ツール
- [Ollama](https://ollama.ai/) - ローカルLLM実行環境
- [vLLM](https://github.com/vllm-project/vllm) - 高速推論ライブラリ
- [LangChain](https://python.langchain.com/) - LLMアプリケーション構築

---

## 🎵 まとめ

UTAMEMOの独自LLM化は、以下の点で大きなメリットがあります：

1. **コスト削減**: API使用料が不要になる
2. **速度向上**: ローカル実行で低レイテンシ
3. **カスタマイズ**: UTAMEMO専用に最適化可能
4. **プライバシー**: ユーザーデータを外部に送信しない

最初は**ファインチューニングアプローチ**から始め、データが蓄積されたら徐々に独自モデルの精度を上げていくのがおすすめです。

---

*このドキュメントは UTAMEMO プロジェクトの将来計画として作成されました。*
*最終更新: 2026年1月*
