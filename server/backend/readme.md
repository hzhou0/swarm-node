# TLDR

## Installation

### Prerequisites
- uv (Python Package Manager): https://docs.astral.sh/uv/getting-started/installation/
Optional:
- node 18 or later (for frontend)
```shell
uv sync --group skymap --group skymapserv
source .venv/bin/activate
xargs sudo apt -y install < required-debs.txt
./src/kernels/skymap/sensor_array/apt-install.sh
```

## Environment Variables
```dotenv
SWARM_NODE_KERNEL=december # more to be added
ICE_SERVERS="" # optional ice_servers in json format, defaults are fine
```