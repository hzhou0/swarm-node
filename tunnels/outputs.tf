output "tunnel_tokens" {
  value = {for k, v in cloudflare_tunnel.nodes : k=>nonsensitive(v.tunnel_token)}
}