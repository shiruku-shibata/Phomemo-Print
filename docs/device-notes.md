# Device notes — Phomemo M02

実機で確認した事実をここに書く。CLAUDE.md の「既知の情報」と食い違ったら、こちらが正。

## 型番

- 箱の表記: （未確認）
- 本体ラベル: （未確認）
- BLE 広告名: （未確認）

## GATT ダンプ

```
# .venv/bin/python tools/explore_gatt.py --name M02 --listen 10 の出力を貼る
```

## 現在の設定値と出典

| 項目 | 値 | 出典 | 実機確認 |
|---|---|---|---|
| サービス | `ff00` | CLAUDE.md 既知の情報 | 未 |
| 書き込み | `ff02` (write without response) | 同上 | 未 |
| 通知 | `ff01`, `ff03` | 同上 | 未 |
| ヘッダ | `1b40 1b6101 1f110204` | vivier/phomemo-tools `tools/phomemo-filter.py` L15 | 未 |
| GS v 0 行数 | 実行数 (`HEIGHT_MINUS_ONE=False`) | ESC/POS 標準。参考実装 L23 は `lines-1` | 未 |
| ブロック行数 | 256 | 参考実装 L77-78 | 未 |
| 0x0A 置換 | しない (`ESCAPE_LF=False`) | 参考実装 L43-46 は 0x14 に置換 | 未 |
| フッタ | `1b6402 ×2 1f1108 1f110e 1f1107 1f1109` | 参考実装 L28-33 | 未 |
| チャンク | `max_write_without_response_size`（上限 512、取得不可なら 128） | — | 未 |
| チャンク間 sleep | 0.02 s | — | 未 |
| 送信後待機 | 1.5 s（`ble.DRAIN_SECONDS`） | — | 未 |

## 印刷テスト記録

変数は 1 つずつ変える。最初は `phomemo -vv test-pattern`（黒ベタ 384×50）。

| 日時 | コマンド | 変えた変数 | 結果 |
|---|---|---|---|
| | `phomemo -vv test-pattern` | （基準） | |
| | `phomemo -vv test-pattern --kind stripes` | | |
| | `phomemo -vv test-pattern --height 300` | 2 ブロック目 | |
| | `phomemo -vv test-pattern --chunk 20` | chunk | |
| | `phomemo -vv test-pattern --delay 0.05` | delay | |

## 通知ログ

`-vv` を付けると ff01 / ff03 の通知が `notify <uuid>: xx xx ...` として出る。気づいたことをここへ。
