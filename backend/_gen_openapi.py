#!/usr/bin/env python
import json
from pathlib import Path

from main import server

with Path(__file__).parent.joinpath("openapi.json").open("w") as f:
    json.dump(server.openapi(), f)
