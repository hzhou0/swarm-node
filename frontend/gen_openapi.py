#!/home/henry/Desktop/shopping_cart/backend/venv/bin/python
# noinspection PyPep8
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import msgspec
import inspect
import shutil

sys.path.insert(1, str(Path(__file__).parent.parent.joinpath("backend").absolute()))
from server import server

npm_bin_dir = Path(__file__).parent.joinpath("node_modules/.bin")
with tempfile.NamedTemporaryFile("w") as f:
    x = server.openapi_schema.to_schema()
    f.write(json.dumps(server.openapi_schema.to_schema()))
    f.flush()
    subprocess.run(
        f"{npm_bin_dir / 'openapi'} --input {f.name} --output src/sdk --client fetch --name Client --useUnionTypes",
        cwd=Path(__file__).parent,
        shell=True,
    )

import models

_models = [getattr(models, m) for m in dir(models)]
_models = [
    m
    for m in _models
    if inspect.isclass(m) and issubclass(m, msgspec.Struct) and m is not msgspec.Struct
]
_, _models = msgspec.json.schema_components(_models, ref_template="{name}")


def resolve_refs(node: dict | list, top_level_models):
    if isinstance(node, dict):
        if "$ref" in node:
            return resolve_refs(top_level_models[node["$ref"]], top_level_models)
        return {
            node_name: resolve_refs(node, top_level_models)
            for node_name, node in node.items()
        }
    if isinstance(node, list):
        return [resolve_refs(node, top_level_models) for node in node]
    return node


_models = resolve_refs(_models, _models)
type_dir = Path(__file__).parent / "types"
type_dir.mkdir(exist_ok=True)
for name, _model in _models.items():
    with open(type_dir / f"{name}.json", "w") as f:
        json.dump(_model, f)

subprocess.run(
    f"{npm_bin_dir/'json2ts'} -i '{type_dir}/*.json' --additionalProperties=false > {Path(__file__).parent/'src'/'models.ts'}",
    cwd=Path(__file__).parent,
    shell=True,
)
shutil.rmtree(type_dir)
