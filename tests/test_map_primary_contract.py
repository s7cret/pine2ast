"""Official map previous-value return and id/id2 source argument contracts."""
import pytest
from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload

TYPES=[('int','2'),('float','2.5'),('bool','false'),('string','"yes"')]

@pytest.mark.parametrize('version',[5,6])
@pytest.mark.parametrize('form',['function','method'])
@pytest.mark.parametrize('named',[False,True])
@pytest.mark.parametrize('dtype,value',TYPES)
def test_put_previous_value_has_the_map_value_type(version,form,named,dtype,value):
    args=f'key="a",value={value}' if named else f'"a",{value}'
    expression=f'map.put(id=a,{args})' if form=='function' and named else f'map.put(a,{args})' if form=='function' else f'a.put({args})'
    source=f'//@version={version}\nindicator("map previous value")\na=map.new<string,{dtype}>()\n{dtype} previous={expression}\n'
    parsed=parse_code(source)
    assert parsed.ok,[(d.code,d.message) for d in parsed.diagnostics]
    call=next(c for c in semantic_facts_payload(parsed)['calls'] if c['symbol_id']==f'pine:{form}:map.put')
    assert call['return_type']==dtype
    assert {a['parameter_name'] for a in call['arguments']}==({'id','key','value'} if form=='function' else {'key','value'})
    assert build_consumer_bundle(source)['content_hash']

@pytest.mark.parametrize('version',[5,6])
@pytest.mark.parametrize('expression,form',[
    ('map.put_all(a,b)','function'),('map.put_all(id=a,id2=b)','function'),
    ('map.put_all(id2=b,id=a)','function'),('a.put_all(b)','method'),('a.put_all(id2=b)','method'),
])
def test_put_all_primary_source_names(version,expression,form):
    source=f'//@version={version}\nindicator("map primary names")\na=map.new<string,int>()\nb=map.new<string,int>()\n{expression}\n'
    parsed=parse_code(source)
    assert parsed.ok,[(d.code,d.message) for d in parsed.diagnostics]
    call=next(c for c in semantic_facts_payload(parsed)['calls'] if c['symbol_id']==f'pine:{form}:map.put_all')
    assert call['return_type']=='void'
    assert {a['parameter_name'] for a in call['arguments']}==({'id','id2'} if form=='function' else {'id2'})
    assert build_consumer_bundle(source)['content_hash']

@pytest.mark.parametrize('version',[5,6])
@pytest.mark.parametrize('expression',[
    'map.put_all(id=a,other=b)','map.put_all(id=a,from=b)',
    'a.put_all(other=b)','a.put_all(from=b)',
    'map.put_all(id=a,id2=3)','map.put_all(id=a,id2=b,id2=b)',
    'map.put(id=a,key=3,value=2)','map.put(id=a,key="a",value="bad")',
])
def test_wrong_map_source_contract_rejects(version,expression):
    source=f'//@version={version}\nindicator("map invalid names")\na=map.new<string,int>()\nb=map.new<string,int>()\n{expression}\n'
    assert not parse_code(source).ok
