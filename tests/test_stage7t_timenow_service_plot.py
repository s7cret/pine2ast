from __future__ import annotations

from pine2ast import parse_code


def test_stage7i_service_plot_corpus_accepts_timenow_as_series_int_builtin() -> None:
    source = '''//@version=6
indicator("s3t realtime DU service plots", overlay=false)
varip int s3t_varip_tick = 0
s3t_varip_tick += 1
plot(s3t_varip_tick)
plot(close)
plot(timenow)
plot(time)
'''

    result = parse_code(source)

    assert result.ast is not None
    messages = [d.message for d in result.diagnostics]
    assert not any('undeclared variable timenow' in message for message in messages)
    assert not any(d.severity.name in {'ERROR', 'FATAL'} for d in result.diagnostics)
