"""Restore the original reviewed source identity; preserve all unrelated refs."""
from pathlib import Path
import json
import os
import subprocess
import sys

BASE = '6ba935eceee505bcbe80bf1f5908588407d2f546'
HEAD = 'a0e548365eba137c247758a3da53c5514398043d'
TREE = 'beab1acecf0620fc72c7c41815f26589ba775f2f'
TARGET = 'refs/heads/release/5.0.0rc6'
STAGE = 'ops/rc6-metadata-transfer-20260906'
RAW = f'tree {TREE}\nparent {BASE}\nauthor OpenPine Review <openpine-review@users.noreply.github.com> 1788711369 +0000\ncommitter OpenPine Review <openpine-review@users.noreply.github.com> 1788711369 +0000\n\nfix(OP-14): validate positional exit actions using the versioned catalog\n\nDo not reject an effective positional profit/limit/loss/stop/trailing call merely because action keywords are absent. Thirty-three regressions cover v1-v6 and quantity-only negative cases.\n'

def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()

def refs():
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote','--refs','origin').splitlines())}

def main():
    if os.environ['GITHUB_REPOSITORY'] != 's7cret/pine2ast':
        raise ValueError('repository mismatch')
    evidence = Path(sys.argv[2]).resolve()
    evidence.mkdir(exist_ok=True, parents=True)
    if sys.argv[1] == 'restore':
        patch = Path('.github/metadata-transfer/change.patch').read_bytes()
        (evidence/'change.patch').write_bytes(patch)
        git('checkout','--detach',BASE)
        git('apply','--check','--index','-',data=patch)
        git('apply','--index','-',data=patch)
        if git('write-tree') != TREE: raise ValueError('reviewed source tree mismatch')
        if git('hash-object','-t','commit','-w','--stdin',data=RAW.encode()) != HEAD:
            raise ValueError('original commit mismatch')
        git('checkout','--detach',HEAD)
        git('update-ref','refs/heads/review-candidate',HEAD)
        git('bundle','create',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
        (evidence/'source-head.txt').write_text(HEAD+'\n')
    elif sys.argv[1] == 'publish':
        if os.environ['GITHUB_REF'] != 'refs/heads/'+STAGE: raise ValueError('wrong staging branch')
        git('fetch',str(evidence/'verified.bundle'),'refs/heads/review-candidate')
        if git('rev-parse','FETCH_HEAD') != HEAD: raise ValueError('bundle mismatch')
        before = refs()
        if before.get(TARGET) not in (BASE,HEAD): raise ValueError('release changed concurrently')
        if before[TARGET] == BASE: git('push','origin',HEAD+':'+TARGET)
        if refs().get(TARGET) != HEAD: raise ValueError('published head mismatch')
        branch, tag = 'refs/heads/'+STAGE, 'refs/tags/'+STAGE
        sha = os.environ['GITHUB_SHA']
        git('push','--atomic',f'--force-with-lease={branch}:{sha}',f'--force-with-lease={tag}:','origin',sha+':'+tag,':'+branch)
        after = refs()
        wanted = {k:v for k,v in before.items() if k.startswith('refs/heads/') and k!=branch}
        wanted[TARGET] = HEAD
        if {k:v for k,v in after.items() if k.startswith('refs/heads/')} != wanted or after.get(tag)!=sha:
            raise ValueError('branch preservation failed')
        for name,value in [('before',before),('after',after)]:
            (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    else: raise ValueError('unknown operation')

if __name__ == '__main__': main()
