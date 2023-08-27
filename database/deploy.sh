#install ~/cloudflarepriv.pem
nano cloudflarepriv.pem
sudo -i
apt-get -y install podman
podman system prune -a
podman pull docker.io/neverlucky135/couchdb:latest
mkdir "$(pwd)"/data
podman run -d --restart always --name couchdb7 -p 443:6984 -v "$(pwd)"/data:/opt/couchdb/data -v "$(pwd)"/cloudflarepriv.pem:/opt/couchdb/etc/cloudflarepriv.pem docker.io/neverlucky135/couchdb:latest
# generate
podman generate systemd --new --name couchdb7 > /etc/systemd/system/couchdb7.service
systemctl enable couchdb7
systemctl start couchdb7