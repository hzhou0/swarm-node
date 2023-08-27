#!/usr/bin/env python3
import pathlib
import subprocess
import shutil
from collections import namedtuple

shared_dir = pathlib.Path(__file__).parent.resolve()
specs_dir = shared_dir / "specs"
Dest = namedtuple("Dest", "dir suffix gen_func")


def pygen(src, dest):
    subprocess.run(f"jsonschema-gentypes --json-schema={src} --python={dest} --python-version=3.8", check=True,
                   shell=True)


def tsgen(src, dest):
    subprocess.run(f"npx --yes json-schema-to-typescript@13.0.1 --input {src} --output {dest}", check=True, shell=True, cwd=shared_dir)


destinations = [Dest(shared_dir.parent / "control" / shared_dir.name, ".d.ts", tsgen),
                Dest(shared_dir.parent / "device" / shared_dir.name, ".py", pygen)]

for dest in destinations:
    if dest.dir.exists():
        shutil.rmtree(dest.dir)
    for spec_file in specs_dir.rglob("*.json"):
        rel_path = spec_file.relative_to(shared_dir).with_suffix(dest.suffix)
        dest_spec_dir = dest.dir / rel_path.parent
        if not dest_spec_dir.exists():
            dest_spec_dir.mkdir(parents=True)
        dest.gen_func(spec_file, dest.dir / rel_path)
        shutil.copy(spec_file, dest.dir)
    shutil.copytree(shared_dir / "constants", dest.dir / "constants")
