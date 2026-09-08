"""Primary modern MACD/TSI parameter qualifiers and exact retained old packs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle

FIXTURES = Path(__file__).with_name('fixtures')
MANUAL_PATH = FIXTURES / 'recursive_length_admission_manual.json'
assert hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest() == 'bb7c32877244350a0fc1f92d7172eba55626352610cd6b965826d0a62297c1aa'
MANUAL = json.loads(MANUAL_PATH.read_bytes())
SCOPE = json.loads((FIXTURES / 'recursive_length_scope.json').read_bytes())
NAMES = {'macd': ['fastlen', 'slowlen', 'siglen'], 'tsi': ['short_length', 'long_length']}


@pytest.mark.parametrize('case', MANUAL['cases'], ids=lambda case: case['id'])
@pytest.mark.parametrize('binding', ['positional', 'named'])
def test_primary_parameter_admission_and_exact_binding(case, binding):
    source = case['source']
    if binding == 'named':
        names = ['source', *NAMES[case['function']]]
        lengths = [2, 3, 2] if case['function'] == 'macd' else [2, 3]
        args = ['close', *map(str, lengths)]
        args[names.index(case['parameter'])] = 'length'
        before = 'ta.' + case['function'] + '(' + ','.join(args) + ')'
        after = 'ta.' + case['function'] + '(' + ','.join(name + '=' + value for name, value in zip(names, args)) + ')'
        assert source.count(before) == 1
        source = source.replace(before, after)
    parsed = parse_code(source)
    if not case['primary_source_admission_expected']:
        assert not parsed.ok
        assert any(d.code == 'P2A1405' and ('Argument ' + case['parameter'] + ' ') in d.message for d in parsed.diagnostics)
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source)
        return
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    bundle = build_consumer_bundle(source)
    call = next(row for row in bundle['semantic_facts']['calls'] if row['callee'] == 'ta.' + case['function'])
    assert call['symbol_id'] == 'pine:function:ta.' + case['function']
    assert call['overload_id'] == call['symbol_id'] + '#canonical'
    assert call['call_form'] == 'NAMESPACE_FUNCTION'
    assert call['return_type'] == ('tuple<float,float,float>' if case['function'] == 'macd' else 'float')
    arg = next(row for row in call['arguments'] if row['parameter_name'] == case['parameter'])
    assert arg['max_qualifier'] == 'simple'
    assert arg['actual_qualifier'] == case['actual_qualifier_kind']
    assert arg['actual_type'] == arg['expected_type'] == 'int'
    assert arg['binding'] == binding
    assert arg['parameter_index'] == NAMES[case['function']].index(case['parameter']) + 1


@pytest.mark.parametrize('version', range(1, 7))
def test_only_five_modern_qualifiers_change_and_old_pack_bytes_remain(version):
    path = Path(__file__).parents[1] / f'pine2ast/catalog_data/packs/pine_v{version}.pack.json'
    raw = path.read_bytes()
    expected = SCOPE['producer_packs'][str(version)]
    if version <= 4:
        assert hashlib.sha256(raw).hexdigest() == expected['before_raw_sha256']
    normalized = deepcopy(json.loads(raw))
    for field in ('source_manifest_hash', 'catalog_hash', 'content_hash'):
        normalized.pop(field)
    encoded = json.dumps(normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected['expected_except_provenance_sha256']
