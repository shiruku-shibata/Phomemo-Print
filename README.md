# phomemo-print

Mac から Phomemo M02 に BLE で画像・テキストを印刷する CLI と Godot 連携サンプル。
仕様は [CLAUDE.md](CLAUDE.md)、実機の確認結果は [docs/device-notes.md](docs/device-notes.md)。

## セットアップ

```sh
cd ~/Desktop/phomemo-print
uv venv --python 3.12 .venv          # または python3.11+ -m venv .venv
uv pip install -e ".[dev]"           # または .venv/bin/pip install -e ".[dev]"
source .venv/bin/activate
pytest
```

システム設定 > プライバシーとセキュリティ > Bluetooth で、実行するアプリ（ターミナル / VS Code / Godot）を許可しておく。

## 使い方

```sh
phomemo scan                      # 近くの M02 を探す（--all で全 BLE デバイス）
phomemo -vv test-pattern          # 黒ベタ 384x50。まずこれで接続確認
phomemo test-pattern --kind stripes
phomemo print photo.png           # 画像を印刷（幅 384px に縮小・ディザ）
phomemo print logo.png --dither threshold --threshold 140
phomemo print photo.jpg --dither atkinson --gamma 1.4 --rotate auto
phomemo print --text "乾杯!"       # テキスト（ヒラギノ角ゴ）。改行は "\n"
phomemo print a.png --text "以上" --preview out.png   # 印刷せずプレビュー保存
phomemo serve --spool spool       # 常駐：spool/ に置かれたファイルを順番に印刷
```

おすすめ設定: ロゴ・線画 → `--dither threshold`、写真 → `--dither atkinson --gamma 1.3`（感熱紙は暗く出がち）。

終了コード: 0 成功 / 1 エラー / 2 プリンター未検出 / 3 入力不正。

## 常駐モード（serve）

- `spool/` に `.png .jpg .bmp .gif .webp`（画像）か `.txt`（テキスト）を置くと、1 つずつ順番に印刷
- 書き込み途中のファイルを拾わないよう、ドットで始まる名前 or `.tmp` で書いてから rename する
- 処理中は `spool/processing/`、成功は `spool/done/`、失敗は `spool/failed/`（`.err` に理由）
- BLE 接続は張りっぱなしで再利用、切れたら自動再接続。プリンターの電源が落ちていても、ジョブは保持して見つかるまで待つ

## Godot

`godot/` を Godot 4 で開いて `sample.tscn` を実行。

- `print_bridge.gd` を自分のシーンに Node として置き、`print_image(img)` / `print_viewport()` / `print_text(s)` を呼ぶ
- **SPOOL モード（推奨）**: 別ターミナルで `phomemo serve --spool spool` を起動しておく。Godot は spool に書くだけなので即座に戻る
- **DIRECT モード**: `OS.execute()` をスレッドで呼ぶ。Godot 側でもキューを持ち、同時に 1 つしか CLI を走らせない
- `phomemo_path` / `spool_dir` は未指定ならプロジェクトの `../.venv/bin/phomemo` と `../spool`

## 印刷がうまくいかないとき

`protocol.py` の定数（`HEIGHT_MINUS_ONE`, `ESCAPE_LF`）と、`--chunk` / `--delay` を 1 つずつ変え、結果を `docs/device-notes.md` に追記する。
