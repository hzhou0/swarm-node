variable "domain" {
  default = "cosmogone.dev"
  type    = string
}

variable "subdomain_suffix" {
  default = "node"
  type    = string
}

variable "account" {
  type    = string
  default = "cosmogone"
}

variable "nodes" {
  type    = set(string)
  default = ["1a", "2a"]
}

variable "node_url" {
  type    = string
  default = "http://localhost:7777"
}

variable "user_emails" {
  type    = set(string)
  default = ["henryzhou000@gmail.com"]
}