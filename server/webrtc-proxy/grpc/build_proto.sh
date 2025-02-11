parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )

cd "$parent_path"
../protoc-29.3-linux-x86_64/bin/protoc --go_out=paths=source_relative:./go --go_opt=default_api_level=API_OPAQUE \
--go-grpc_out=paths=source_relative:./go ./networking.proto


uvx --from grpcio-tools python -m grpc_tools.protoc -I=. \
  --pyi_out=./python/src/webrtc_proxy \
  --python_out=./python/src/webrtc_proxy \
  --grpc_python_out=./python/src/webrtc_proxy \
  ./networking.proto
