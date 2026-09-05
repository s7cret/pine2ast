"""Restore SHA-checked source patches; no arbitrary generation commands are accepted."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOS = {'s7cret/openpine','s7cret/pine2ast','s7cret/pinelib','s7cret/ast2python'}
TARGET = 'refs/heads/release/5.0.0rc6'
STAGING = 'ops/rc6-requests-20260906'


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()


def load(path):
    plan = json.loads(path.read_text())
    if plan['repository'] not in REPOS or plan['repository'] != os.environ.get('GITHUB_REPOSITORY',plan['repository']):
        raise ValueError('repository identity mismatch')
    if plan['target'] != TARGET.removeprefix('refs/heads/') or plan['expected'] not in (None, plan['base']):
        raise ValueError('target identity mismatch')
    parent = plan['base']
    for item in plan['commits']:
        if any(not re.fullmatch('[0-9a-f]{40}',item[k]) for k in ('sha','parent','tree')) or item['parent'] != parent:
            raise ValueError('invalid/noncontiguous reviewed series')
        raw = item['raw'].encode()
        if not raw.startswith(f"tree {item['tree']}\nparent {parent}\nauthor ".encode()):
            raise ValueError('commit header identity mismatch')
        if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != item['sha']:
            raise ValueError('reviewed commit SHA mismatch')
        if item['regenerate'] not in (None,'pinelib_manifest','pine_catalog') or (item['regenerate']=='pinelib_manifest' and plan['repository']!='s7cret/pinelib') or (item['regenerate']=='pine_catalog' and plan['repository']!='s7cret/pine2ast'):
            raise ValueError('unapproved generation step')
        parent = item['sha']
    if parent != plan['head']:
        raise ValueError('wrong reviewed head')
    return plan


def restore(path,evidence):
    plan = load(path); evidence.mkdir(parents=True, exist_ok=True)
    (evidence/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    patches=[]
    for item in plan['commits']:
        chunks=[]
        for name in item['parts']:
            if not re.fullmatch(r'[0-9]{2}-[0-9]{2}\.patch',name):
                raise ValueError('invalid patch path')
            data=(path.parent/name).read_bytes()
            if len(data)>2000000:
                raise ValueError('oversized patch')
            chunks.append(data);(evidence/name).write_bytes(data)
        patch=b''.join(chunks)
        if hashlib.sha256(patch).hexdigest()!=item['patch_sha256']:
            raise ValueError('patch checksum mismatch')
        patches.append(patch)
    git('checkout','--detach',plan['base'])
    for item,patch in zip(plan['commits'],patches,strict=True):
        if git('rev-parse','HEAD') != item['parent']:
            raise ValueError('working parent mismatch')
        git('apply','--check','--index','-',data=patch)
        git('apply','--index','--whitespace=nowarn','-',data=patch)
        if item['regenerate']=='pinelib_manifest':
            subprocess.run([sys.executable,'-c',
                "from pathlib import Path; from pinelib.abi.builder import write_manifest; write_manifest(Path('pinelib/abi/target_manifest.json'))"],
                check=True,env={**os.environ,'PYTHONPATH':str(Path.cwd())})
            git('add','pinelib/abi/target_manifest.json')
        if item['regenerate']=='pine_catalog':
            subprocess.run([sys.executable,'tools/catalog/build_catalog.py'],check=True)
            git('add','catalog_reports/migration_report.json','catalog_source','pine2ast/catalog_data/packs')
        if git('write-tree') != item['tree']:
            raise ValueError('restored source tree differs from reviewed source')
        if git('hash-object','-t','commit','-w','--stdin',data=item['raw'].encode()) != item['sha']:
            raise ValueError('restored commit identity mismatch')
        git('checkout','--detach',item['sha'])
    git('update-ref','refs/heads/review-candidate',plan['head'])
    git('bundle','create',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    git('bundle','verify',str(evidence/'verified.bundle'))
    (evidence/'restored-head').write_text(plan['head']+'\n')


def refs():
    return {ref: sha for sha,ref in (line.split() for line in git('ls-remote','--heads','origin').splitlines())}


def publish(evidence):
    plan=load(evidence/'plan.json')
    if os.environ.get('GITHUB_REF')!='refs/heads/'+STAGING:
        raise ValueError('wrong publication branch')
    git('fetch',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
    if git('rev-parse','FETCH_HEAD')!=plan['head']:
        raise ValueError('bundle head mismatch')
    git('merge-base','--is-ancestor',plan['base'],plan['head'])
    before=refs(); current=before.get(TARGET)
    if current not in (plan['expected'],plan['head']):
        raise ValueError('release changed concurrently; refusing overwrite')
    if current!=plan['head']:
        git('push','origin',plan['head']+':'+TARGET)
    if refs().get(TARGET)!=plan['head']:
        raise ValueError('release publication verification failed')
    (evidence/'published-head').write_text(plan['head']+'\n')
    branch,tag='refs/heads/'+STAGING,'refs/tags/'+STAGING
    sha=os.environ['GITHUB_SHA']
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('invalid maintenance head')
    git('push','--atomic',f'--force-with-lease={branch}:{sha}',f'--force-with-lease={tag}:','origin',sha+':'+tag,':'+branch)
    expected={**before,TARGET:plan['head']};expected.pop(branch)
    after=refs()
    if after!=expected or git('ls-remote','--refs','origin',tag).split()[0]!=sha:
        raise ValueError('archive or final branch inventory mismatch')
    (evidence/'before.json').write_text(json.dumps(before,indent=2)+'\n')
    (evidence/'after.json').write_text(json.dumps(after,indent=2)+'\n')
    (evidence/'archive.txt').write_text(tag+' '+sha+'\n')


if __name__=='__main__':
    if sys.argv[1]=='restore': restore(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
    elif sys.argv[1]=='publish': publish(Path(sys.argv[2]).resolve())
    else: raise ValueError('unknown operation')
