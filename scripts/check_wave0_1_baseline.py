#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys, tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def vt(s):
    m=re.match(r'^(\d+)\.(\d+)\.(\d+)', s or '')
    return tuple(map(int,m.groups())) if m else (0,0,0)
def lockver(lock,name):
    d=json.loads(lock.read_text())
    x=d.get('packages',{}).get('node_modules/'+name)
    return (x or {}).get('version')
def lockvers(lock,name):
    d=json.loads(lock.read_text())
    suffix='node_modules/'+name
    out=[]
    for path,item in d.get('packages',{}).items():
        if path == suffix or path.endswith('/'+suffix):
            v=(item or {}).get('version')
            if v:
                out.append((path,v))
    return out
def vite_is_patched(version):
    major, minor, patch=vt(version)
    if major == 6:
        return (major,minor,patch) >= (6,4,3)
    if major == 7:
        return (major,minor,patch) >= (7,3,5)
    if major == 8:
        return (major,minor,patch) >= (8,0,16)
    return major > 8
ap=argparse.ArgumentParser(); ap.add_argument('--strict',action='store_true'); a=ap.parse_args()
errors=[]; pending=[]
def require(cond,msg):
    if not cond: errors.append(msg)
require((ROOT/'.nvmrc').read_text().strip()=='24.19.0','.nvmrc must pin Node 24.19.0')
require((ROOT/'.node-version').read_text().strip()=='24.19.0','.node-version must pin Node 24.19.0')
ci=(ROOT/'.github/workflows/ci.yml').read_text()
require('node-version: "20"' not in ci,'root CI still references Node 20')
require('npm install' not in ci,'root CI still uses npm install instead of npm ci')
for rel in ['frontend/Dockerfile','frontend/Dockerfile.prod','docs/portal/Dockerfile']:
    s=(ROOT/rel).read_text()
    require('node:20' not in s,f'{rel} still references Node 20')
    require('npm install' not in s,f'{rel} still uses npm install')
py=tomllib.loads((ROOT/'backend/pyproject.toml').read_text())
deps=py['project']['dependencies']
require(any(x.startswith('python-jose[cryptography]>=3.5.0') for x in deps),'python-jose safe floor missing')
require(any(x.startswith('python-multipart>=0.0.32') for x in deps),'python-multipart safe floor missing')
require(any(x.startswith('openai>=1.40,<2.0') for x in deps),'OpenAI SDK major cap missing')
fl=ROOT/'frontend/package-lock.json'
nuxt=lockver(fl,'nuxt'); devtools=lockver(fl,'@nuxt/devtools'); types=lockver(fl,'@types/node')
if vt(nuxt) < (4,5,1): pending.append(f'frontend lock Nuxt is {nuxt}; need >=4.5.1')
if vt(devtools) < (3,3,1): pending.append(f'frontend lock @nuxt/devtools is {devtools}; need >=3.3.1')
resolved_vite=lockvers(fl,'vite')
if not resolved_vite:
    pending.append('frontend lock contains no Vite package')
else:
    for path,version in resolved_vite:
        if not vite_is_patched(version):
            pending.append(f'frontend lock {path} is Vite {version}; require patched lane >=6.4.3, >=7.3.5, or >=8.0.16')
if not types or vt(types)[0] != 24: pending.append(f'frontend lock @types/node is {types}; target major 24')
locks_ok=True
for name in ['requirements.lock','requirements-dev.lock']:
    p=ROOT/'backend'/name
    if not p.exists(): pending.append(f'backend/{name} not generated'); locks_ok=False
    elif '--hash=sha256:' not in p.read_text(): errors.append(f'backend/{name} is not hash enforced'); locks_ok=False
if locks_ok:
    import hashlib
    mp=ROOT/'backend/dependency-lock-metadata.json'
    if not mp.exists():
        errors.append('backend/dependency-lock-metadata.json missing')
    else:
        meta=json.loads(mp.read_text())
        sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        if meta.get('pyproject_sha256') != sha(ROOT/'backend/pyproject.toml'):
            errors.append('backend lock metadata is stale relative to pyproject.toml')
        if meta.get('requirements_lock_sha256') != sha(ROOT/'backend/requirements.lock'):
            errors.append('requirements.lock checksum differs from lock metadata')
        if meta.get('requirements_dev_lock_sha256') != sha(ROOT/'backend/requirements-dev.lock'):
            errors.append('requirements-dev.lock checksum differs from lock metadata')
print('Wave 0.1 baseline check')
print('  structural errors:', len(errors))
for x in errors: print('   ERROR:',x)
print('  connected-resolution pending:', len(pending))
for x in pending: print('   PENDING:',x)
if errors or (a.strict and pending): sys.exit(1)
