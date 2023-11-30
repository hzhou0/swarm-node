#!/home/henry/Desktop/shopping_cart/backend/venv/bin/python
# noinspection PyPep8
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(1, str(Path(__file__).parent.parent.joinpath("backend").absolute()))
from api import server

with tempfile.NamedTemporaryFile("w") as f:
    f.write(json.dumps(server.openapi_schema.to_schema()))
    f.flush()
    openapi_bin = Path(__file__).parent.joinpath("node_modules/.bin/openapi")
    subprocess.run(
        f"{openapi_bin} --input {f.name} --output src/sdk --client fetch --name Client --useUnionTypes",
        cwd=Path(__file__).parent,
        shell=True,
    )
