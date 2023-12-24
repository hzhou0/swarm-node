post_install(){
# Add cloudflare gpg key
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

# Add this repo to your apt repositories
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' | sudo tee /etc/apt/sources.list.d/cloudflared.list

# install cloudflared
sudo apt-get update
sudo apt-get install -y cloudflared
# Add ulimit configurations for all users
echo "* hard nofile 1048576" | sudo tee -a /etc/security/limits.conf
echo "* soft nofile 1048576" | sudo tee -a /etc/security/limits.conf
sudo tee "/etc/sddm.conf" > /dev/null << EOL
[Autologin]
User=node
Session=lxqt.desktop
Relogin=true
EOL
sudo tee "/etc/nftables.conf" > /dev/null << EOL
#!/usr/sbin/nft -f

flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Allow loopback traffic
        iifname "lo" accept

        # Allow local traffic
        ip saddr { 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12 } accept

        # Webrtc Traffic
        udp dport { 3478, 10000-65535 } accept
        tcp dport { 443, 10000-65535 } accept
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }
}
EOL
sudo systemctl enable nftables.service
}
post_install > /home/node/post_install.log 2>&1