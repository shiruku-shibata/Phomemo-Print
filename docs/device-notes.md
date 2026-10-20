# Device notes — Phomemo M02

実機で確認した事実をここに書く。CLAUDE.md の「既知の情報」と食い違ったら、こちらが正。

## 型番

- 箱の表記: （未確認）
- 本体ラベル: （未確認）
- BLE 広告名: `Mr.in_M02`（2026-10-06）。「M02」で始まらないので、名前は部分一致で探す
- 広告サービス: `af30`, `1812`（`ff00` は広告しない）。manufacturer 0x0000: `d1 16 a7 ac 00 7c`

## GATT ダンプ

```
[service] 0000ff00-...  Vendor specific
  [char] ff01  handle=5  props=read                          max_wwr=197   value: b''
  [char] ff02  handle=7  props=write-without-response,write  max_wwr=197
  [char] ff03  handle=9  props=notify                        max_wwr=197
## Notifications (5s, idle)
  ff03: 01 01
  ff03: 02 b6 00
```

- ff01 は read のみ（notify 非対応）。通知は ff03 だけ
- 1回の書き込み上限は 197 バイト → chunk = 197

## 現在の設定値と出典

| 項目 | 値 | 出典 | 実機確認 |
|---|---|---|---|
| サービス | `ff00` | CLAUDE.md 既知の情報 | 済 |
| 書き込み | `ff02` (write without response) | 同上 | 済 |
| 通知 | `ff03` のみ（ff01 は read） | 実機 GATT ダンプ | 済 |
| ヘッダ | `1b40 1b6101 1f110204` | vivier/phomemo-tools `tools/phomemo-filter.py` L15 | 未 |
| GS v 0 行数 | 実行数 (`HEIGHT_MINUS_ONE=False`) | ESC/POS 標準。参考実装 L23 は `lines-1` | 未 |
| ブロック行数 | 256 | 参考実装 L77-78 | 未 |
| 0x0A 置換 | しない (`ESCAPE_LF=False`) | 参考実装 L43-46 は 0x14 に置換 | 未 |
| フッタ | `1b6402 ×2 1f1108 1f110e 1f1107 1f1109` | 参考実装 L28-33 | 未 |
| チャンク | `max_write_without_response_size` = 197 | 実機 GATT ダンプ | 済 |
| チャンク間 sleep | 0.02 s | — | 未 |
| 送信後待機 | 1.5 s（`ble.DRAIN_SECONDS`） | — | 未 |

## 印刷テスト記録

変数は 1 つずつ変える。最初は `phomemo -vv test-pattern`（黒ベタ 384×50）。

| 日時 | コマンド | 変えた変数 | 結果 |
|---|---|---|---|
| 2026-10-06 19:05 | `phomemo -vv test-pattern` | （基準） | 送信は完了（2435 bytes / 197 bytes ずつ）。送信中 ff03 に `01 01` が連続。紙の出方は確認待ち |
| | `phomemo -vv test-pattern --kind stripes` | | |
| | `phomemo -vv test-pattern --height 300` | 2 ブロック目 | |
| | `phomemo -vv test-pattern --chunk 20` | chunk | |
| | `phomemo -vv test-pattern --delay 0.05` | delay | |

## 通知ログ

`-vv` を付けると ff01 / ff03 の通知が `notify <uuid>: xx xx ...` として出る。気づいたことをここへ。
