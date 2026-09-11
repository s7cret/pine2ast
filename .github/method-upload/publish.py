"""Publish exact reviewed commits to candidate refs, without updating releases."""
from __future__ import annotations
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()


def refs():
    return {ref: sha for sha, ref in (r.split() for r in git('ls-remote', '--refs', 'origin').splitlines())}


folder=Path('.github/method-upload')
plan=json.loads((folder/'plan.json').read_text())
if plan['repo']!=os.environ['GITHUB_REPOSITORY'] or plan['repo'] not in {'s7cret/pine2ast','s7cret/ast2python','s7cret/openpine'}:
    raise SystemExit('repository mismatch')
for key in ('base','head','tree'):
    if not re.fullmatch('[0-9a-f]{40}',plan[key]): raise SystemExit('invalid source identity')
parts=sorted(folder.glob('part*.b64'))
if not parts or [p.name for p in parts]!=[f'part{i:02}.b64' for i in range(len(parts))]:
    raise SystemExit('incomplete source parts')
compressed=base64.b64decode(''.join(p.read_text().strip() for p in parts),validate=True)
if hashlib.sha256(compressed).hexdigest()!=plan['payload_sha256']: raise SystemExit('payload checksum mismatch')
patch=gzip.decompress(compressed)
if len(patch)>2_000_000 or hashlib.sha256(patch).hexdigest()!=plan['patch_sha256']:
    raise SystemExit('patch checksum mismatch')
raw=plan['raw_commit'].encode()
if not raw.startswith(f"tree {plan['tree']}\nparent {plan['base']}\nauthor ".encode()):
    raise SystemExit('unexpected source commit header')
if hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=plan['head']:
    raise SystemExit('source commit identity mismatch')
branch='refs/heads/ops/publish-library-methods-20260911'
archive='refs/tags/ops/publish-library-methods-20260911'
candidate='refs/heads/stage2/library-methods-20260911'
if os.environ['GITHUB_REF']!=branch: raise SystemExit('wrong publication branch')
sha=os.environ['GITHUB_SHA']
before=refs()
if before.get(branch)!=sha or before.get(candidate) not in (None,plan['head']) or archive in before:
    raise SystemExit('concurrent publication or conflicting ref')
git('checkout','--detach',plan['base'])
git('apply','--check','--index','-',data=patch)
git('apply','--index','--whitespace=nowarn','-',data=patch)
if git('write-tree')!=plan['tree'] or git('diff','--cached','--name-only').splitlines()!=plan['files']:
    raise SystemExit('reviewed source tree or path inventory differs')
if git('hash-object','-t','commit','-w','--stdin',data=raw)!=plan['head']:
    raise SystemExit('written commit mismatch')
git('checkout','--detach',plan['head'])
args=['push','--atomic','--force-with-lease='+branch+':'+sha,'--force-with-lease='+archive+':']
updates=[sha+':'+archive,':'+branch]
if candidate not in before:
    args.append('--force-with-lease='+candidate+':')
    updates.append(plan['head']+':'+candidate)
git(*args,'origin',*updates)
after=refs()
expected={ref:head for ref,head in before.items() if ref!=branch}
expected.update({archive:sha,candidate:plan['head']})
if after!=expected: raise SystemExit('unexpected final refs')
evidence=Path(os.environ['RUNNER_TEMP'])/'publication';evidence.mkdir()
(evidence/'source.patch').write_bytes(patch)
(evidence/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
for name,data in [('before',before),('after',after)]:
    (evidence/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
git('update-ref','refs/heads/delivery-source',plan['head'])
git('bundle','create',str(evidence/'source.bundle'),'refs/heads/delivery-source')
git('bundle','verify',str(evidence/'source.bundle'))
(evidence/'receipt.json').write_text(json.dumps({'repo':plan['repo'],'head':plan['head'],'tree':plan['tree'],'candidate':candidate,'release_changed':False,'tests_run':False},indent=2)+'\n')
