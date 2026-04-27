# v2.12.0 corpus/quality run status

Полный corpus/quality прогон по `tests/fixtures/real_world` был запущен, но окружение снова сорвало выполнение внешними helper-процессами вида:

```text
python -c import json, os; p = json.loads("/mnt/data/work_v29/...")
```

Эти процессы проверяли старые `/mnt/data/work_v28` и `/mnt/data/work_v29` пути, потребляли CPU и приводили к таймаутам даже на коротких CLI smoke-командах.

Фактически завершённые проверки v2.12.0:

```text
stdlib runner: 167 passed
focused v2.12 tests: 11 passed
builtin coverage: function_count=276, missing_expected=0
schema smoke 01_ma_indicator.pine: parse_ok=true, schema.ok=true
```

Остаток для чистого окружения:

```bash
python -S -m pine2ast.cli validate-corpus tests/fixtures/real_world --json CORPUS_RUN_v2_12_0.json
python -S -m pine2ast.cli quality-gate tests/fixtures/real_world --json QUALITY_GATE_v2_12_0.json
```
