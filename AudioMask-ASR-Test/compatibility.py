"""Metadata-only audit: PyPI JSON and wheel tags, no package/weight downloads.

Uses packaging bundled with pip (no installation). This is a conservative graph
walk, not a replacement for pip's resolver or a Windows model smoke test.
"""
import datetime
import json
from pathlib import Path
import sys
import urllib.request
from collections import defaultdict, deque
from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.tags import cpython_tags, compatible_tags
from pip._vendor.packaging.utils import parse_wheel_filename, canonicalize_name
from pip._vendor.packaging.version import Version, InvalidVersion

ROOT = Path(__file__).resolve().parent
CACHE = {}


def fetch(url):
    if url not in CACHE:
        req = urllib.request.Request(url, headers={'User-Agent':'AudioMask-ASR-metadata-audit/1.0'})
        with urllib.request.urlopen(req, timeout=45) as response:
            CACHE[url] = json.load(response)
    return CACHE[url]


def audit_profile(model, minor):
    env = default_environment()
    env.update(python_version=f'3.{minor}', python_full_version=f'3.{minor}.0',
        sys_platform='win32', platform_system='Windows', platform_machine='AMD64',
        os_name='nt', platform_python_implementation='CPython', implementation_name='cpython',
        implementation_version=f'3.{minor}.0', extra='')
    tags = set(cpython_tags((3,minor), abis=[f'cp3{minor}'], platforms=['win_amd64']))
    tags.update(compatible_tags((3,minor), interpreter=f'cp3{minor}', platforms=['win_amd64']))
    requirements = [Requirement(line.strip()) for line in (ROOT/f'requirements-{model}.txt').read_text().splitlines()
        if line.strip() and not line.startswith('#')]
    constraints, chosen = defaultdict(list), {}
    queue = deque(requirements)
    while queue:
        req = queue.popleft()
        if req.marker and not req.marker.evaluate(env):
            continue
        name = canonicalize_name(req.name)
        if str(req.specifier) not in constraints[name]:
            constraints[name].append(str(req.specifier))
        specs = SpecifierSet(','.join(constraints[name]))
        if name in chosen and specs.contains(chosen[name]['version']):
            continue
        project = fetch(f'https://pypi.org/pypi/{name}/json')
        candidates = []
        for ver in project['releases']:
            try:
                parsed = Version(ver)
            except InvalidVersion:
                continue
            if not parsed.is_prerelease and specs.contains(ver):
                candidates.append(parsed)
        selected = None
        for parsed in sorted(candidates, reverse=True):
            wheels, sources = [], []
            for entry in project['releases'][str(parsed)]:
                if entry.get('yanked') or not SpecifierSet(entry.get('requires_python') or '').contains(f'3.{minor}.0'):
                    continue
                filename = entry['filename']
                if filename.endswith('.whl'):
                    try:
                        if parse_wheel_filename(filename)[3] & tags:
                            wheels.append(filename)
                    except ValueError:
                        pass
                elif entry['packagetype'] == 'sdist':
                    sources.append(filename)
            if wheels or (name == 'antlr4-python3-runtime' and sources):
                selected = dict(version=str(parsed), compatible_wheels=wheels,
                    source_only_exception=sources if not wheels else [], constraints=constraints[name].copy())
                break
        if selected is None:
            raise ValueError(f'{model}/3.{minor}: no compatible artifact for {name}{specs}')
        if name in chosen and chosen[name]['version'] != selected['version']:
            raise ValueError(f'Graph revision for {name}; use pip resolve to handle backtracking')
        chosen[name] = selected
        metadata = fetch(f"https://pypi.org/pypi/{name}/{selected['version']}/json")
        deps = []
        for value in metadata['info'].get('requires_dist') or []:
            dependency = Requirement(value)
            if not dependency.marker or dependency.marker.evaluate(env):
                deps.append(value)
                queue.append(dependency)
        selected['dependencies'] = deps
    return chosen


def main():
    evidence = dict(generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        method='PyPI metadata graph + wheel tags; no installs; no binary or weight downloads',
        limitation='No backtracking; no runtime guarantee; CPU-index packages require on-VM resolution/import check',
        profiles={}, model_revisions={})
    failed = False
    for model in ('whisper','gigaam-v3','gigaam-multi'):
        for minor in (12,13):
            key = f'{model}/3.{minor}'
            try:
                graph = audit_profile(model, minor)
                evidence['profiles'][key] = dict(status='metadata-compatible', packages=graph)
                print(key, 'metadata-compatible;', len(graph), 'packages', flush=True)
            except Exception as e:
                failed = True
                evidence['profiles'][key] = dict(status='unresolved', error=str(e))
                print(key, 'unresolved:', e, flush=True)
    for name, repo, revision in (
        ('whisper','Systran/faster-whisper-small','main'),
        ('gigaam-v3','ai-sage/GigaAM-v3','ctc'),
        ('gigaam-multi','ai-sage/GigaAM-Multilingual','ctc')):
        try:
            metadata = fetch(f'https://huggingface.co/api/models/{repo}/revision/{revision}')
            evidence['model_revisions'][name] = dict(repository=repo, revision=revision, commit=metadata['sha'])
        except Exception as e:
            evidence['model_revisions'][name] = dict(error=str(e))
            failed = True
    folder = ROOT/'compatibility'
    folder.mkdir(exist_ok=True)
    (folder/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved:', folder/'evidence.json')
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
