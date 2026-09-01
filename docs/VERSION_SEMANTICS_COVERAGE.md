# Pine2AST 5.0.0rc6 — покрытие семантики по версиям

Показатели ниже относятся к **статическому frontend Pine2AST**. Они не являются заявлением о runtime-паритете с TradingView.

| Pine | Audited static requirements | Internal symbols | Callables | Operators | Frontend status |
|---:|---:|---:|---:|---:|---|
| v1 | 20/20 | 780 | 211 | 13 | `HISTORICAL_STATIC_SNAPSHOT` |
| v2 | 19/19 | 789 | 211 | 15 | `HISTORICAL_STATIC_SNAPSHOT` |
| v3 | 15/15 | 789 | 211 | 15 | `HISTORICAL_STATIC_SNAPSHOT` |
| v4 | 20/20 | 1015 | 356 | 20 | `HISTORICAL_STATIC_SNAPSHOT` |
| v5 | 21/21 | 1325 | 644 | 20 | `STATIC_COMPLETE` |
| v6 | 21/21 | 1511 | 713 | 21 | `STATIC_COMPLETE` |

## Граница заявления

- `100% audited static requirements` означает, что все требования из version-semantic inventory имеют реализацию и автоматическую проверку в текущей поставке.
- `100% internal catalog structure` означает отсутствие пропусков относительно hash-bound version packs этой поставки.
- Полнота всей исторической поверхности TradingView, PineLib runtime, Broker Emulator и TradingView oracle здесь не заявляется.
