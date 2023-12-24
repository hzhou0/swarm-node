terraform {
  required_version = "~> 1.5.7"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
  backend "s3" {
    bucket                      = "tfstate"
    key                         = "tfstate/terraform.tfstate"
    endpoint                    = "https://6f64e8b16964731dd9f9dd00af7a3af6.r2.cloudflarestorage.com/tfstate"
    skip_credentials_validation = true
    skip_region_validation      = true
    region                      = "us-east-1"
  }
}

data "cloudflare_zone" "zone" {
  name = var.domain
}

data "cloudflare_accounts" "account" {
  name = var.account
}

locals {
  account_id = one(data.cloudflare_accounts.account.accounts).id
  zone_id    = data.cloudflare_zone.zone.zone_id
  subdomains = {for agent in var.nodes : agent=>"${agent}-${var.subdomain_suffix}.${var.domain}"}
}

resource cloudflare_access_application "swarm" {
  account_id          = local.account_id
  name                = "Swarm"
  domain              = values(local.subdomains)[0]
  self_hosted_domains = values(local.subdomains)
  type                = "self_hosted"

  app_launcher_visible       = true
  enable_binding_cookie      = true
  http_only_cookie_attribute = true
  same_site_cookie_attribute = "strict"
  session_duration           = "24h"
}


resource "random_id" "tunnel_secrets" {
  for_each    = var.nodes
  byte_length = 32
}

resource "cloudflare_tunnel" "nodes" {
  for_each   = var.nodes
  account_id = local.account_id
  name       = local.subdomains[each.key]
  secret     = random_id.tunnel_secrets[each.key].b64_std
  config_src = "cloudflare"
}

resource "cloudflare_tunnel_config" "app" {
  for_each   = var.nodes
  account_id = local.account_id
  tunnel_id  = cloudflare_tunnel.nodes[each.key].id
  config {
    origin_request {
      access {
        required = true
        aud_tag  = [cloudflare_access_application.swarm.aud]
      }
    }
    ingress_rule {
      service  = var.node_url
      hostname = local.subdomains[each.key]
    }
    ingress_rule {
      service = "http_status:404"
    }
  }
}

resource "cloudflare_record" "subdomain" {
  for_each = var.nodes
  zone_id  = local.zone_id
  name     = local.subdomains[each.key]
  type     = "CNAME"
  proxied  = true
  value    = cloudflare_tunnel.nodes[each.key].cname
}

resource "cloudflare_access_policy" "app_policy" {
  application_id = cloudflare_access_application.swarm.id
  account_id     = local.account_id
  decision       = "allow"
  name           = "default"
  precedence     = 1
  include {
    email = var.user_emails
  }
}