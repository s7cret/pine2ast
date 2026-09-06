"""Reconstruct reviewed source; publish only a verified fast-forward.

Transport chunks are checked as Git blobs; the decoded readable diff, generated
files, full tree and raw source commit must all have their reviewed identities.
"""
from __future__ import annotations
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

STAGING = 'ops/rc6-stage2-language-20260907'
TARGET = 'refs/heads/release/5.0.0rc6'
REPOS = {'s7cret/pine2ast','s7cret/pinelib','s7cret/ast2python','s7cret/openpine'}


def git(*args, data=None, cwd=None):
    return subprocess.check_output(['git', *args],input=data,cwd=cwd).decode().strip()


def load(path):
    p=json.loads(path.read_text())
    if p['repository'] not in REPOS or os.environ.get('GITHUB_REPOSITORY',p['repository'])!=p['repository']:
        raise ValueError('repository mismatch')
    if p['target']!=TARGET.removeprefix('refs/heads/'):
        raise ValueError('target mismatch')
    for field in ('base','base_tree','head','tree'):
        if not re.fullmatch('[0-9a-f]{40}',p[field]): raise ValueError('invalid source identity')
    raw=p['raw'].encode()
    if not raw.startswith(f"tree {p['tree']}\nparent {p['base']}\nauthor ".encode()):
        raise ValueError('raw header mismatch')
    if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=p['head']:
        raise ValueError('raw commit mismatch')
    return p


def restore(submission, evidence):
    p=load(submission/'plan.json')
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'plan.json').write_text(json.dumps(p,indent=2)+'\n')
    chunks=[]
    for name,sha in p['chunks'].items():
        if not re.fullmatch(r'source\.[0-9]{3}\.b64',name): raise ValueError('invalid chunk path')
        data=(submission/name).read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=sha: raise ValueError('chunk mismatch: '+name)
        chunks.append((name,data))
    compressed=base64.b64decode(b''.join(data for _,data in sorted(chunks)),validate=True)
    if hashlib.sha256(compressed).hexdigest()!=p['compressed_sha256']:
        raise ValueError('compressed checksum mismatch')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        patch=stream.read(2_000_001)
    if len(patch)>2_000_000 or hashlib.sha256(patch).hexdigest()!=p['patch_sha256']:
        raise ValueError('readable patch checksum mismatch')
    (evidence/'source.patch').write_bytes(patch)
    dependencies=Path(os.environ['RUNNER_TEMP'])/'dependencies'
    dependencies.mkdir(exist_ok=True)
    sources=[]
    for name,sha in p['dependencies'].items():
        if not re.fullmatch(r'[a-z0-9_-]+',name) or not re.fullmatch('[0-9a-f]{40}',sha):
            raise ValueError('invalid dependency identity')
        path=dependencies/name
        subprocess.run(['git','clone','--quiet','https://github.com/s7cret/'+name+'.git',str(path)],check=True)
        git('checkout','--detach',sha,cwd=path)
        if git('rev-parse','HEAD',cwd=path)!=sha: raise ValueError('wrong dependency')
        clean=dependencies/(name+'-install');clean.mkdir()
        subprocess.run(['tar','-x','-C',str(clean)],input=subprocess.check_output(['git','archive',sha],cwd=path),check=True)
        sources.append(str(clean))
    if sources:
        subprocess.run([sys.executable,'-m','pip','install',*sources],check=True)
    git('checkout','--detach',p['base'])
    if git('rev-parse','HEAD^{tree}')!=p['base_tree']: raise ValueError('base tree mismatch')
    git('apply','--check','--index','-',data=patch)
    git('apply','--index','--whitespace=nowarn','-',data=patch)
    for command in p['regenerate']:
        command=[a.replace('${DEPS}',str(dependencies)) for a in command]
        if command[0]!='python': raise ValueError('invalid regeneration command')
        subprocess.run([sys.executable,*command[1:]],check=True)
    git('add','-A')
    if git('write-tree')!=p['tree']: raise ValueError('regenerated source tree differs from review')
    if git('hash-object','-t','commit','-w','--stdin',data=p['raw'].encode())!=p['head']:
        raise ValueError('restored commit mismatch')
    git('checkout','--detach',p['head'])
    git('update-ref','refs/heads/review-candidate',p['head'])
    git('bundle','create',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    git('bundle','verify',str(evidence/'verified.bundle'))
    (evidence/'source-head.txt').write_text(p['head']+'\n')
    clean=Path(os.environ['RUNNER_TEMP'])/'build-source';clean.mkdir()
    subprocess.run(['tar','-x','-C',str(clean)],input=subprocess.check_output(['git','archive','HEAD']),check=True)
    package=str(clean)+('' if p['repository'].endswith('/pinelib') else '[dev]')
    subprocess.run([sys.executable,'-m','pip','install',package],check=True)


def validate(evidence):
    import xml.etree.ElementTree as ET
    p=load(evidence/'plan.json')
    cases=ET.parse(evidence/'tests.xml').getroot().findall('.//testcase')
    if len(cases)!=p['expected_tests'] or any(c.find(tag) is not None for c in cases for tag in ('failure','error','skipped')):
        raise ValueError('full required suite did not pass')
    if p['changed_python']:
        subprocess.run([sys.executable,'-m','ruff','check',*p['changed_python']],check=True)
    if git('status','--porcelain','--untracked-files=no'): raise ValueError('dirty tested source')


def refs():
    return {ref:sha for sha,ref in (line.split() for line in git('ls-remote','--refs','origin').splitlines())}


def publish(evidence):
    p=load(evidence/'plan.json')
    branch,tag='refs/heads/'+STAGING,'refs/tags/'+STAGING
    sha=os.environ['GITHUB_SHA']
    if os.environ.get('GITHUB_REF')!=branch or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('wrong publication ref')
    git('fetch',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    if git('rev-parse','FETCH_HEAD')!=p['head']: raise ValueError('wrong bundle')
    git('merge-base','--is-ancestor',p['base'],p['head'])
    before=refs()
    if before.get(TARGET) not in (p['base'],p['head']): raise ValueError('concurrent release change')
    if before[TARGET]!=p['head']: git('push','origin',p['head']+':'+TARGET)
    if refs().get(TARGET)!=p['head']: raise ValueError('publication not confirmed')
    git('push','--atomic',f'--force-with-lease={branch}:{sha}',f'--force-with-lease={tag}:','origin',sha+':'+tag,':'+branch)
    after=refs()
    expected={k:v for k,v in before.items() if k.startswith('refs/heads/') and k!=branch}
    expected[TARGET]=p['head']
    if {k:v for k,v in after.items() if k.startswith('refs/heads/')}!=expected or after.get(tag)!=sha:
        raise ValueError('branch preservation mismatch')
    for name,value in [('before',before),('after',after)]:
        (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    (evidence/'published-head.txt').write_text(p['head']+'\n')


if __name__=='__main__':
    if sys.argv[1]=='restore': restore(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
    elif sys.argv[1]=='validate': validate(Path(sys.argv[2]).resolve())
    elif sys.argv[1]=='publish': publish(Path(sys.argv[2]).resolve())
    else: raise ValueError('unknown operation')
