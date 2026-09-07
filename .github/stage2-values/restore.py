"""Restore one exact reviewed source commit; never force a release ref."""
from __future__ import annotations
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOS={'s7cret/pine2ast','s7cret/pinelib','s7cret/ast2python','s7cret/openpine'}
STAGING='refs/heads/ops/stage2-values-20260907'
TARGET='refs/heads/release/5.0.0rc6'

def git(*args,data=None):
    return subprocess.check_output(['git',*args],input=data).decode().strip()

def load(path):
    p=json.loads(path.read_text())
    if p['repository'] not in REPOS or p['repository']!=os.environ['GITHUB_REPOSITORY']:
        raise ValueError('repository mismatch')
    if any(not re.fullmatch('[0-9a-f]{40}',p[k]) for k in ('base','head','tree')):
        raise ValueError('invalid source identity')
    raw=p['raw'].encode()
    if not raw.startswith(f"tree {p['tree']}\nparent {p['base']}\nauthor ".encode()):
        raise ValueError('commit header mismatch')
    if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=p['head']:
        raise ValueError('raw commit checksum mismatch')
    if type(p['regenerate']) is not bool or (p['regenerate'] and p['repository']!='s7cret/pinelib'):
        raise ValueError('unapproved generation step')
    return p

def restore(folder,evidence):
    p=load(folder/'plan.json');evidence.mkdir(parents=True,exist_ok=True)
    compressed=base64.b64decode((folder/'source.gz.b64').read_text().strip(),validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        patch=stream.read(2_000_001)
    if len(patch)>2_000_000 or hashlib.sha256(patch).hexdigest()!=p['patch_sha256']:
        raise ValueError('source patch checksum mismatch')
    (evidence/'plan.json').write_text(json.dumps(p,indent=2)+'\n')
    (evidence/'source.patch').write_bytes(patch)
    git('checkout','--detach',p['base'])
    git('apply','--check','--index','-',data=patch)
    git('apply','--index','--whitespace=nowarn','-',data=patch)
    if p['regenerate']:
        subprocess.run([sys.executable,'-c',"from pathlib import Path; from pinelib.abi.builder import write_manifest; write_manifest(Path('pinelib/abi/target_manifest.json'))"],check=True,env={**os.environ,'PYTHONPATH':str(Path.cwd())})
        git('add','pinelib/abi/target_manifest.json')
    if git('write-tree')!=p['tree']: raise ValueError('source tree differs from reviewed tree')
    if git('hash-object','-t','commit','-w','--stdin',data=p['raw'].encode())!=p['head']:
        raise ValueError('restored commit identity mismatch')
    git('checkout','--detach',p['head'])
    git('update-ref','refs/heads/review-candidate',p['head'])
    git('bundle','create',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    git('bundle','verify',str(evidence/'verified.bundle'))
    (evidence/'source-head.txt').write_text(p['head']+'\n')
    (evidence/'source-tree.txt').write_text(p['tree']+'\n')

def refs():
    return {ref:sha for sha,ref in (x.split() for x in git('ls-remote','--refs','origin').splitlines())}

def publish(evidence):
    p=load(evidence/'plan.json')
    if os.environ['GITHUB_REF']!=STAGING: raise ValueError('wrong staging ref')
    before=refs();tip=os.environ['GITHUB_SHA'];tag=STAGING.replace('refs/heads/','refs/tags/',1)
    if before.get(TARGET) not in (p['base'],p['head']) or before.get(STAGING)!=tip:
        raise ValueError('concurrent ref change')
    git('fetch',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    if git('rev-parse','FETCH_HEAD')!=p['head']: raise ValueError('verified bundle mismatch')
    git('merge-base','--is-ancestor',p['base'],p['head'])
    if before[TARGET]!=p['head']: git('push','origin',p['head']+':'+TARGET)
    if refs().get(TARGET)!=p['head']: raise ValueError('release update not confirmed')
    git('push','--atomic',f'--force-with-lease={STAGING}:{tip}',f'--force-with-lease={tag}:','origin',tip+':'+tag,':'+STAGING)
    after=refs();expected={**before,TARGET:p['head'],tag:tip};expected.pop(STAGING)
    if after!=expected: raise ValueError('final ref inventory mismatch')
    for name,value in [('before',before),('after',after)]:
        (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    (evidence/'published-head.txt').write_text(p['head']+'\n')

if __name__=='__main__':
    if sys.argv[1]=='restore': restore(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
    elif sys.argv[1]=='publish': publish(Path(sys.argv[2]).resolve())
    else: raise ValueError('unknown operation')
