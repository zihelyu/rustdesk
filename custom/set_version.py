#!/usr/bin/env python3
"""Synchronize the next public version before committing/building."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', help='numeric x.y.z, greater than the currently released version')
    parser.add_argument('--android-code', type=int, required=True, help='integer greater than the previous Android build number')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.version) or any(int(x) > 65535 for x in args.version.split('.')):
        parser.error('version must be x.y.z with each segment <= 65535')
    root = Path(__file__).resolve().parents[1]
    cargo = (root / 'Cargo.toml').read_text()
    old = re.search(r'^version = "([^"]+)"', cargo, re.M)[1]
    flutter = (root / 'flutter/pubspec.yaml').read_text()
    old_code = int(re.search(r'^version: [^+]+\+(\d+)', flutter, re.M)[1])
    if tuple(map(int,args.version.split('.'))) <= tuple(map(int,old.split('.'))):
        parser.error('new version must be greater than current version')
    if not old_code < args.android_code <= 2100000000:
        parser.error('Android code must increase and be <= 2100000000')
    edits = {
        'Cargo.toml': (r'^version = "'+re.escape(old)+r'"$', f'version = "{args.version}"'),
        'Cargo.lock': (r'(\[\[package\]\]\nname = "rustdesk"\nversion = ")[^"]+("$)', rf'\g<1>{args.version}\g<2>'),
        'flutter/pubspec.yaml': (r'^version: .+$', f'version: {args.version}+{args.android_code}'),
        '.github/workflows/flutter-build.yml': (r'^  VERSION: "[^"]+".*$', f'  VERSION: "{args.version}"'),
    }
    rendered={}
    for filename,(pattern,replacement) in edits.items():
        text,count=re.subn(pattern,replacement,(root/filename).read_text(),flags=re.M)
        if count!=1: raise ValueError(f'{filename}: expected one version field, found {count}')
        rendered[filename]=text
    for filename,text in rendered.items():(root/filename).write_text(text)
    print(f'Updated four version fields to {args.version}; Android code {args.android_code}. Commit these files before building.')

if __name__=='__main__':main()
