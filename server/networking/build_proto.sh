parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )

cd "$parent_path"
./protoc-29.3-linux-x86_64/bin/protoc --go_out=paths=source_relative:./ipc --python_out=:./python_sdk --pyi_out=:./python_sdk --go_opt=default_api_level=API_OPAQUE ./networking.proto