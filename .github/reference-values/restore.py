"""Materialize an exact source candidate; never advance a release before joint CI."""
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

FEATURE = 'refs/heads/stage2/reference-values-20260907'
MAINT = 'refs/heads/ops/stage2-reference-values-20260907'
RELEASE = 'refs/heads/release/5.0.0rc6'
ALLOWED = {'s7cret/pine2ast', 's7cret/pinelib', 's7cret/ast2python'}


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()


def refs():
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}


def materialize(source: Path, evidence: Path):
    plan = json.loads((source / 'plan.json').read_text())
    if plan['repository'] not in ALLOWED or os.environ['GITHUB_REPOSITORY'] != plan['repository']:
        raise ValueError('repository mismatch')
    if os.environ['GITHUB_REF'] != MAINT:
        raise ValueError('wrong maintenance ref')
    for name in ('base', 'head', 'tree'):
        if not re.fullmatch('[0-9a-f]{40}', plan[name]):
            raise ValueError('invalid source identity')
    if type(plan['regenerate_manifest']) is not bool or plan['regenerate_manifest'] != (plan['repository'] == 's7cret/pinelib'):
        raise ValueError('unapproved regeneration request')
    raw = plan['raw'].encode()
    if not raw.startswith(f"tree {plan['tree']}\nparent {plan['base']}\nauthor ".encode()):
        raise ValueError('commit header mismatch')
    expected = hashlib.sha1(b'commit ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if expected != plan['head']:
        raise ValueError('raw commit hash mismatch')
    compressed = base64.b64decode((source / 'source.b64').read_text().strip(), validate=True)
    if len(compressed) > 2_000_000:
        raise ValueError('compressed source exceeds limit')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        patch = stream.read(2_000_001)
    if len(patch) > 2_000_000 or hashlib.sha256(patch).hexdigest() != plan['patch_sha256']:
        raise ValueError('source patch hash/size mismatch')
    before = refs()
    maintenance_sha = os.environ['GITHUB_SHA']
    if before.get(MAINT) != maintenance_sha or before.get(RELEASE) != plan['base']:
        raise ValueError('concurrent branch change')
    if before.get(FEATURE) not in (None, plan['head']):
        raise ValueError('candidate already has unrelated work')
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    (evidence / 'source.patch').write_bytes(patch)
    git('checkout', '--detach', plan['base'])
    git('apply', '--check', '--index', '-', data=patch)
    git('apply', '--index', '--whitespace=nowarn', '-', data=patch)
    changed = git('diff', '--cached', '--name-only').splitlines()
    if any(path.startswith(('.git/', '.github/')) for path in changed):
        raise ValueError('candidate source must not change workflow permissions')
    if plan['regenerate_manifest']:
        subprocess.run([sys.executable, '-c',
            "from pathlib import Path; from pinelib.abi.builder import write_manifest; write_manifest(Path('pinelib/abi/target_manifest.json'))"],
            check=True, env={**os.environ, 'PYTHONPATH': str(Path.cwd())})
        git('add', 'pinelib/abi/target_manifest.json')
    if git('write-tree') != plan['tree']:
        raise ValueError('reconstructed tree differs from reviewed source')
    if git('hash-object', '-t', 'commit', '-w', '--stdin', data=raw) != plan['head']:
        raise ValueError('reconstructed commit differs')
    git('checkout', '--detach', plan['head'])
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('dirty candidate')
    git('update-ref', 'refs/heads/review-candidate', plan['head'])
    git('bundle', 'create', str(evidence / 'source.bundle'), 'refs/heads/review-candidate')
    git('bundle', 'verify', str(evidence / 'source.bundle'))
    if before.get(FEATURE) != plan['head']:
        git('push', 'origin', plan['head'] + ':' + FEATURE)
    after = refs()
    if after.get(FEATURE) != plan['head'] or after.get(RELEASE) != plan['base']:
        raise ValueError('candidate publication mismatch')
    tag = MAINT.replace('refs/heads/', 'refs/tags/', 1)
    git('push', '--atomic', '--force-with-lease=' + MAINT + ':' + maintenance_sha,
        '--force-with-lease=' + tag + ':', 'origin', maintenance_sha + ':' + tag, ':' + MAINT)
    final = refs()
    expected_refs = {**before, FEATURE: plan['head'], tag: maintenance_sha}
    expected_refs.pop(MAINT)
    if final != expected_refs:
        raise ValueError('unexpected ref change during publication')
    for name, value in [('before', before), ('after', final)]:
        (evidence / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')
    (evidence / 'candidate-head.txt').write_text(plan['head'] + '\n')
    (evidence / 'scope.txt').write_text('Source materialization only. Release unchanged. Joint CI still required.\n')


if __name__ == '__main__':
    materialize(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
