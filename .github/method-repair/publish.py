"""Checksum-bound source upload to the existing candidate, never a release."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()


def refs():
    return {ref:sha for sha,ref in (line.split() for line in git('ls-remote','--refs','origin').splitlines())}


root=Path(sys.argv[1]).resolve()
plan=json.loads((root/'plan.json').read_text())
if plan['repository']!=os.environ['GITHUB_REPOSITORY'] or plan['branch']!='stage2/library-methods-20260911':
    raise SystemExit('wrong candidate/repository')
branch='refs/heads/'+plan['branch']
maintenance='refs/heads/ops/stage2-method-repair-20260911'
archive=maintenance.replace('refs/heads/','refs/tags/',1)
sha=os.environ['GITHUB_SHA']
if os.environ['GITHUB_REF']!=maintenance:
    raise SystemExit('wrong publication ref')
parent=plan['base']; patches=[]
for i,item in enumerate(plan['commits'],1):
    if item['parent']!=parent or any(not re.fullmatch('[0-9a-f]{40}',item[k]) for k in ('sha','tree','parent')):
        raise SystemExit('bad commit chain')
    raw=item['raw'].encode()
    if not raw.startswith(('tree '+item['tree']+'\nparent '+parent+'\nauthor ').encode()):
        raise SystemExit('bad raw commit')
    if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=item['sha']:
        raise SystemExit('raw commit identity mismatch')
    patch=(root/f'{i:02}.patch').read_bytes()
    if hashlib.sha256(patch).hexdigest()!=item['patch_sha256']:
        raise SystemExit('patch checksum mismatch')
    patches.append(patch);parent=item['sha']
if parent!=plan['head']:
    raise SystemExit('wrong plan head')
evidence=Path(os.environ['RUNNER_TEMP'])/'publication';evidence.mkdir(exist_ok=True)
(evidence/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
git('checkout','--detach',plan['base'])
for item,patch in zip(plan['commits'],patches,strict=True):
    git('apply','--check','--index','-',data=patch)
    git('apply','--index','--whitespace=nowarn','-',data=patch)
    if git('write-tree')!=item['tree']:
        raise SystemExit('exact source tree mismatch')
    if git('hash-object','-t','commit','-w','--stdin',data=item['raw'].encode())!=item['sha']:
        raise SystemExit('exact source commit mismatch')
    git('checkout','--detach',item['sha'])
before=refs()
if before.get(branch) not in (plan['base'],plan['head']) or before.get(maintenance)!=sha or archive in before:
    raise SystemExit('concurrent changes; release refs untouched')
git('push','origin',plan['head']+':'+branch)
git('push','--atomic','--force-with-lease='+maintenance+':'+sha,'--force-with-lease='+archive+':','origin',sha+':'+archive,':'+maintenance)
after=refs();expected={k:v for k,v in before.items() if k!=maintenance};expected.update({branch:plan['head'],archive:sha})
if after!=expected:
    raise SystemExit('unexpected remote ref change')
git('update-ref','refs/heads/exported-candidate',plan['head'])
git('bundle','create',str(evidence/'source.bundle'),'refs/heads/exported-candidate')
for name,value in [('before',before),('after',after)]:
    (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
(evidence/'receipt.json').write_text(json.dumps({'repository':plan['repository'],'head':plan['head'],'tree':git('rev-parse','HEAD^{tree}'),'release_changed':False,'functional_ci_run':False},indent=2)+'\n')
