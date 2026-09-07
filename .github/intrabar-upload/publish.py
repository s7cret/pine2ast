"""Preserve exact local commits as tags; never modify release heads."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def refs():
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}


repo = os.environ['SOURCE_REPOSITORY']
if os.environ['GITHUB_REPOSITORY'] != repo:
    raise SystemExit('repository mismatch')
head = os.environ['SOURCE_HEAD']
tree = os.environ['SOURCE_TREE']
base = os.environ['SOURCE_BASE']
branch = 'refs/heads/ops/publish-intrabar-20260907'
tag = 'refs/tags/local/stage2-intrabar-20260907'
archive = 'refs/tags/ops/publish-intrabar-20260907'
sha = os.environ['GITHUB_SHA']
if os.environ['GITHUB_REF'] != branch:
    raise SystemExit('wrong upload branch')
parts = sorted(Path('.github/intrabar-upload/parts').glob('part*'))
if [p.name for p in parts] != [f'part{i:02}' for i in range(int(os.environ['SOURCE_PARTS']))]:
    raise SystemExit('missing or unexpected part')
data = base64.b64decode(''.join(p.read_text() for p in parts), validate=True)
if hashlib.sha256(data).hexdigest() != os.environ['SOURCE_BUNDLE_SHA256']:
    raise SystemExit('original bundle checksum mismatch')
evidence = Path(os.environ['RUNNER_TEMP']) / 'publication'
evidence.mkdir()
bundle = evidence / 'source.bundle'
bundle.write_bytes(data)
git('bundle', 'verify', str(bundle))
git('fetch', str(bundle), 'refs/heads/stage2/varip-collections-20260907')
if git('rev-parse', 'FETCH_HEAD') != head or git('rev-parse', head + '^{tree}') != tree or git('rev-parse', head + '^') != base:
    raise SystemExit('original commit/tree/parent mismatch')
before = refs()
if before.get(branch) != sha or before.get(tag) not in (None, head) or archive in before:
    raise SystemExit('conflicting or concurrent upload')
args = ['push', '--atomic', '--force-with-lease=' + branch + ':' + sha, '--force-with-lease=' + archive + ':']
updates = [sha + ':' + archive, ':' + branch]
if tag not in before:
    args.append('--force-with-lease=' + tag + ':')
    updates.append(head + ':' + tag)
git(*args, 'origin', *updates)
after = refs()
expected = {key: value for key, value in before.items() if key != branch}
expected.update({tag: head, archive: sha})
if after != expected:
    raise SystemExit('post-upload refs differ from exact plan')
receipt = {'repository': repo, 'head': head, 'tree': tree, 'base': base, 'tag': tag, 'release_changed': False, 'tests_run': False, 'full_stage2_accepted': False}
for name, value in [('before', before), ('after', after), ('receipt', receipt)]:
    (evidence / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
