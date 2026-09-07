"""Verify reviewed patch/tree/commit identities before a guarded RC6 fast-forward."""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

STAGING='refs/heads/ops/stage2-intrabar-20260907'
TARGET='refs/heads/release/5.0.0rc6'
ALLOWED={'s7cret/pine2ast','s7cret/pinelib','s7cret/ast2python','s7cret/openpine'}


def git(*args,data=None):
    return subprocess.check_output(['git',*args],input=data).decode().strip()


def load(path):
    p=json.loads(path.read_text())
    if p['repository'] not in ALLOWED or p['repository']!=os.environ['GITHUB_REPOSITORY']:
        raise ValueError('repository mismatch')
    if any(not re.fullmatch('[0-9a-f]{40}',p[k]) for k in ('head','base','tree')):
        raise ValueError('invalid source identities')
    raw=p['raw'].encode()
    if not raw.startswith(f"tree {p['tree']}\nparent {p['base']}\nauthor ".encode()):
        raise ValueError('invalid commit header')
    if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=p['head']:
        raise ValueError('commit hash mismatch')
    return p


def restore(folder,out):
    p=load(folder/'plan.json')
    compressed=(folder/'source.patch.gz').read_bytes()
    if len(compressed)>2_000_000 or hashlib.sha256(compressed).hexdigest()!=p['compressed_sha256']:
        raise ValueError('compressed patch integrity mismatch')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
        patch=f.read(8_000_001)
    if len(patch)>8_000_000 or hashlib.sha256(patch).hexdigest()!=p['patch_sha256']:
        raise ValueError('source patch integrity mismatch')
    out.mkdir(parents=True,exist_ok=True)
    (out/'plan.json').write_text(json.dumps(p,indent=2)+'\n')
    (out/'source.patch').write_bytes(patch)
    git('checkout','--detach',p['base'])
    git('apply','--check','--index','-',data=patch)
    git('apply','--index','--whitespace=nowarn','-',data=patch)
    if p.get('regenerate_manifest'):
        if p['repository']!='s7cret/pinelib':
            raise ValueError('unexpected regeneration policy')
        subprocess.run([sys.executable,'-m','pinelib.abi','build'],check=True)
        git('add','pinelib/abi/target_manifest.json')
    if git('write-tree')!=p['tree']:
        raise ValueError('reconstructed tree differs from reviewed source')
    if git('hash-object','-t','commit','-w','--stdin',data=p['raw'].encode())!=p['head']:
        raise ValueError('reconstructed commit mismatch')
    git('checkout','--detach',p['head'])
    if git('status','--porcelain','--untracked-files=no'):
        raise ValueError('dirty reconstructed source')
    git('update-ref','refs/heads/verified-intrabar',p['head'])
    git('bundle','create',str(out/'source.bundle'),'refs/heads/verified-intrabar')
    git('bundle','verify',str(out/'source.bundle'))
    git('archive','--format=tar.gz','--output='+str(out/'source.tar.gz'),'HEAD')
    (out/'source-head.txt').write_text(p['head']+'\n')
    (out/'source-tree.txt').write_text(p['tree']+'\n')


def refs():
    return {ref:sha for sha,ref in (line.split() for line in git('ls-remote','--refs','origin').splitlines())}


def publish(out):
    p=load(out/'plan.json')
    if os.environ.get('GITHUB_REF')!=STAGING:
        raise ValueError('wrong publication ref')
    maintenance=os.environ['GITHUB_SHA']
    git('fetch',str(out/'source.bundle'),'refs/heads/verified-intrabar')
    if git('rev-parse','FETCH_HEAD')!=p['head']:
        raise ValueError('verified bundle mismatch')
    git('merge-base','--is-ancestor',p['base'],p['head'])
    before=refs()
    if before.get(TARGET) not in (p['base'],p['head']):
        raise ValueError('release changed concurrently')
    if before.get(STAGING) not in (None,maintenance):
        raise ValueError('maintenance ref changed concurrently')
    tag=STAGING.replace('refs/heads/','refs/tags/',1)
    if tag in before and before[tag]!=maintenance:
        raise ValueError('archive tag conflict')
    if before[TARGET]!=p['head']:
        git('push','origin',p['head']+':'+TARGET)
    changes=[];leases=[]
    if tag not in before:
        changes.append(maintenance+':'+tag);leases.append('--force-with-lease='+tag+':')
    if STAGING in before:
        changes.append(':'+STAGING);leases.append('--force-with-lease='+STAGING+':'+maintenance)
    if changes:
        git('push','--atomic',*leases,'origin',*changes)
    after=refs()
    expected={k:v for k,v in before.items() if k.startswith('refs/heads/') and k!=STAGING}
    expected[TARGET]=p['head']
    if {k:v for k,v in after.items() if k.startswith('refs/heads/')}!=expected or after.get(tag)!=maintenance:
        raise ValueError('final ref preservation failed')
    for name,values in [('before',before),('after',after)]:
        (out/(name+'.json')).write_text(json.dumps(values,indent=2)+'\n')
    (out/'published-head.txt').write_text(p['head']+'\n')


if __name__=='__main__':
    if sys.argv[1]=='restore':restore(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
    elif sys.argv[1]=='publish':publish(Path(sys.argv[2]).resolve())
    else:raise ValueError('unknown operation')
