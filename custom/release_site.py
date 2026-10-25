#!/usr/bin/env python3
"""Build a static update site using the upstream signed metadata format."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / 'custom/branding.json').read_text(encoding='utf-8'))


def check_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    encoded = os.environ.get('RUSTDESK_UPDATE_ED25519_SEED', '')
    seed = base64.b64decode(encoded, validate=True)
    if len(seed) != 32 or base64.b64encode(seed).decode() != encoded:
        raise ValueError('Missing/invalid RUSTDESK_UPDATE_ED25519_SEED secret')
    derived = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if base64.b64encode(derived).decode() != config()['update_public_key']:
        raise ValueError('Update secret does not match custom/branding.json public key')


def check_ci():
    check_key()
    for name in ['ANDROID_SIGNING_KEY', 'ANDROID_ALIAS', 'ANDROID_KEY_STORE_PASSWORD', 'ANDROID_KEY_PASSWORD']:
        if not os.environ.get(name):
            raise ValueError(f'Missing repository secret: {name}; see local-setup/')
    version = source_version()
    workflow = (ROOT / '.github/workflows/flutter-build.yml').read_text()
    if not re.search(r'^  VERSION: "' + re.escape(version) + r'"$', workflow, re.M):
        raise ValueError('Workflow VERSION differs from Cargo.toml version')
    if not re.search(r'^version: ' + re.escape(version) + r'\+', (ROOT / 'flutter/pubspec.yaml').read_text(), re.M):
        raise ValueError('Flutter version differs from Cargo.toml version')
    print('Configuration, version and signing secrets validated.')


def source_version():
    return re.search(r'^version = "([^"]+)"', (ROOT / 'Cargo.toml').read_text(), re.M)[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(artifacts_dir, output, version):
    check_key()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) or version != source_version():
        raise ValueError('Release version must equal Cargo.toml x.y.z version')
    cfg = config()
    origin = cfg['update_origin']
    output = output.resolve()
    if output.exists():
        raise ValueError('Output directory already exists; choose a fresh directory')
    files = {}
    extensions = ('.exe', '.msi', '.apk', '.deb', '.rpm', '.dmg', '.AppImage', '.flatpak', '.pkg.tar.zst')
    for path in sorted(artifacts_dir.rglob('*')):
        if not path.is_file() or not path.name.endswith(extensions):
            continue
        if not re.fullmatch(r'[A-Za-z0-9._-]+', path.name) or path.stat().st_size == 0:
            raise ValueError(f'Invalid artifact: {path.name}')
        if version not in path.name:
            raise ValueError(f'Artifact version mismatch: {path.name}')
        if path.name in files:
            raise ValueError(f'Duplicate artifact: {path.name}')
        files[path.name] = path
    # The Windows updater needs exactly these architecture/format combinations.
    selectors = {}
    for arch in ('x86_64', 'aarch64'):
        for fmt in ('exe', 'msi'):
            selectors[f'rustdesk-{version}-{arch}.{fmt}'] = ('windows', arch, fmt)
    selectors[f'rustdesk-{version}-x86-sciter.exe'] = ('windows', 'x86', 'exe')
    for arch in ('x86_64', 'aarch64'):
        name = f'rustdesk-{version}-{arch}.dmg'
        if name in files:
            selectors[name] = ('macos', arch, 'dmg')
    missing = selectors.keys() - files.keys()
    if missing:
        raise ValueError('Missing update artifacts: ' + ', '.join(sorted(missing)))
    dest = output / 'releases/download' / version
    dest.mkdir(parents=True)
    for name, path in files.items():
        shutil.copyfile(path, dest / name)
    common = ['--version', version, '--release-id', version, '--package-id', 'rustdesk',
              '--release-base-url', origin + '/releases/download']
    metadata = dest / 'rustdesk-update.json'
    signature = dest / 'rustdesk-update.json.sig'
    generator = ROOT / 'res/update/generate_update_metadata.py'
    command = [sys.executable, str(generator), 'sign', *common, '--published-at',
               datetime.now(timezone.utc).isoformat(), '--metadata-out', str(metadata), '--signature-out', str(signature)]
    for name, selector in selectors.items():
        command += ['--artifact', *selector, str(dest / name)]
    subprocess.run(command, check=True)
    verify = [sys.executable, str(generator), 'verify', *common, '--metadata', str(metadata), '--signature', str(signature)]
    for name in selectors:
        verify += ['--artifact', str(dest / name)]
    env = os.environ.copy()
    env['RUSTDESK_UPDATE_ED25519_PUBLIC_KEY'] = cfg['update_public_key']
    subprocess.run(verify, env=env, check=True)
    page_url = origin + '/releases/tag/' + version
    (output / 'version').mkdir()
    (output / 'version/latest.json').write_text(json.dumps({'url': page_url}) + '\n')
    checksums = ''.join(f'{sha256(dest / name)}  {name}\n' for name in sorted(files))
    (dest / 'SHA256SUMS').write_text(checksums)
    links = ''.join(f'<li><a href="/releases/download/{version}/{html.escape(name)}">{html.escape(name)}</a></li>' for name in sorted(files))
    title = html.escape(cfg['display_name']) + ' ' + version
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:16px/1.7 system-ui;max-width:960px;margin:48px auto;padding:0 20px}}a{{color:#1260a8}}li{{overflow-wrap:anywhere}}</style>
<h1>{title}</h1><p>公司内部远程协助客户端。请根据设备系统和架构下载安装包。</p>
<h2>版本说明</h2><p>保留公司品牌、默认连接配置及远程协助定制，接入公司 API 和更新服务。</p>
<h2>下载安装</h2><ul>{links}</ul><p><a href="/releases/download/{version}/SHA256SUMS">文件校验值</a></p></html>'''
    for relative in ('download/index.html', f'releases/tag/{version}/index.html'):
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding='utf-8')
    print(f'Update site created: {len(files)} packages; signature and file hashes verified.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check-ci', 'build'])
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    if args.command == 'check-ci':
        check_ci()
    else:
        if not all((args.artifacts, args.output, args.version)):
            parser.error('build requires --artifacts, --output and --version')
        build(args.artifacts, args.output, args.version)


if __name__ == '__main__':
    main()
