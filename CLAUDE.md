# phomemo-print — 指示書

Phomemo M02（感熱プリンター）に、Mac から BLE 経由で任意の画像を印刷するプロジェクト。
最終的には Godot から画像を渡して印刷できるようにする（展示用途を想定）。

## ゴール（完了条件）

1. `phomemo scan` で近くの M02 が見つかる
2. `phomemo print path/to/image.png` で画像がそのまま印刷される（幅 384px に収まる白黒）
3. `phomemo print --text "乾杯!"` でテキストも印刷できる
4. Godot から `OS.execute()` で CLI を呼んで印刷できる（サンプルシーン付き）
5. 連続で印刷要求が来ても詰まらない（キュー化）

## 前提・環境

- macOS（Apple Silicon）、Python 3.11+（pyenv）、venv
- 主要ライブラリ: `bleak`（BLE / CoreBluetooth）、`Pillow`、`click`（CLI）、`pytest`
- 実機: Phomemo M02（今日届く）。**型番は箱・本体で必ず確認**（M02 / M02S / M02 Pro で解像度と幅が違う）

## 既知の情報（ネット調査ベース・すべて実機で要検証）

- BLE GATT: サービス `ff00`、書き込み `ff02`、通知 `ff01` / `ff03`
- macOS では MAC アドレスが取れず CoreBluetooth の UUID になる → **デバイス名 or サービス UUID でスキャン**する
- macOS の bleak は `pair()` 非対応。ペアリングは不要な想定（必要ならOSのダイアログが出る）
- 書き込みは `response=False`（Write Without Response）で、`max_write_without_response_size` 程度にチャンク分割し、チャンク間に短い sleep を入れる
- コマンドは ESC/POS 系＋独自拡張。M02 の想定シーケンス:
  - ヘッダ: `1B 40` + `1B 61 01` + `1F 11 02 04`
  - 画像: `1D 76 30 00` + 幅バイト数(LE 2byte, 384px なら 48) + 行数(LE 2byte) + ラスタデータ
    - 1ブロック最大 256 行程度に分割して送る
  - フッタ: `1B 64 02` ×2 + `1F 11 08` `1F 11 0E` `1F 11 07` `1F 11 09`
- 参考実装: `vivier/phomemo-tools`（Linux/CUPS、M02 対応）、`hkeward/phomemo_printer`、`ryo-endo/phomemo-printer`（M02 Pro × bleak）

## ディレクトリ構成

```
phomemo-print/
├── CLAUDE.md
├── pyproject.toml
├── src/phomemo/
│   ├── ble.py          # スキャン・接続・チャンク送信（ble-driver 担当）
│   ├── protocol.py     # コマンドバイト列の組み立て（ble-driver 担当）
│   ├── raster.py       # 画像→1bitラスタ変換（raster-pipeline 担当）
│   ├── text.py         # テキスト→画像（raster-pipeline 担当）
│   ├── queue.py        # 印刷キュー（メイン）
│   └── cli.py          # click CLI（メイン）
├── tools/
│   └── explore_gatt.py # サービス/キャラクタリスティック一覧ダンプ
├── godot/              # Godot 連携サンプル（メイン）
└── tests/
```

## 進め方（フェーズ）

### Phase 0: 実機確認（メインが実施、最初に必ず）
- システム設定 > プライバシーとセキュリティ > Bluetooth で、ターミナル / VS Code に許可を出す
- `tools/explore_gatt.py` で広告名・サービス・キャラクタリスティック・プロパティを全部ダンプし、`docs/device-notes.md` に記録
- 上の「既知の情報」と食い違ったら、そちらを正として以後の作業を進める

### Phase 1: 並列実装（サブエージェント2体に委譲）
- **ble-driver**: `ble.py` / `protocol.py`。テスト用に「黒ベタ 384×50」を印刷できるところまで
- **raster-pipeline**: `raster.py` / `text.py`。実機なしで単体テスト完結
- 両者の境界は下の「インターフェース契約」で固定する。契約を変えたいときはメインに戻す

### Phase 2: 結合・CLI
- `cli.py` で `scan` / `print <image>` / `print --text` / `test-pattern`
- `--dither {floyd,threshold,atkinson}` `--threshold N` `--preview out.png`（印刷せずに変換結果だけ保存）

### Phase 3: Godot 連携
- `godot/print_bridge.gd`: Viewport や Image を PNG 保存 → `OS.execute()` で CLI 呼び出し
- 印刷はブロッキングするので Thread か `OS.create_process()` で非同期に
- 二重送信防止のため、CLI 側に常駐モード（`phomemo serve`、ローカルのソケット or スプールフォルダ監視）を用意してキューで捌く案を検討

## インターフェース契約

```python
# raster.py
@dataclass
class Raster:
    width_px: int        # 8の倍数。M02 は 384
    height_px: int
    data: bytes          # 1行 = width_px // 8 バイト、MSB が左、1 = 黒

def image_to_raster(img: PIL.Image.Image, width_px: int = 384,
                    dither: str = "floyd", threshold: int = 128) -> Raster: ...

# protocol.py
def build_print_job(raster: Raster, feed_lines: int = 2) -> bytes: ...

# ble.py
async def find_printer(name_prefix: str = "M02", timeout: float = 10.0) -> BLEDevice: ...
async def send(device: BLEDevice, payload: bytes, chunk: int | None = None,
               delay: float = 0.02) -> None: ...
```

## ルール

- 実機を叩く処理と純粋ロジックを分ける。純粋ロジックは必ず pytest を書く
- プロトコルの推測値は定数にまとめ、出典（参考実装のファイル/行 or 実機ログ）をコメントで残す
- うまく印刷できないときは、まずヘッダ/フッタ・チャンクサイズ・sleep を1つずつ変えて `docs/device-notes.md` に結果を追記
- 印刷テストは紙の無駄を減らすため、高さ 50px 程度の小さいパターンから始める
- 秘密情報なし。コミットは小さく、Phase ごとに区切る
