#install cloudflarepriv.pem
nano cloudflarepriv.pem
sudo apt-get -y install podman
sudo podman system prune -a
sudo podman pull docker.io/neverlucky135/couchdb:latest
sudo mkdir "$(pwd)"/data
sudo podman run -d --restart always -p 443:6984 -v "$(pwd)"/data:/opt/couchdb/data -v "$(pwd)"/cloudflarepriv.pem:/opt/couchdb/etc/cloudflarepriv.pem docker.io/neverlucky135/couchdb:latest
# deploy TURN server
sudo podman run -d --restart always --network=host docker.io/coturn/coturn --log-file=stdout --no-auth --no-tls --no-dtls