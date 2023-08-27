terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "4.79.0"
    }
  }
}

provider "google" {
  project = "seventhletter"
  region  = "us-central1"
  zone    = "us-central1-c"
}

variable "cloudflare_pem" {
  type        = string
  description = "String containing cloudflare PEM"
  sensitive   = true
  nullable    = false
}

resource "google_compute_instance" "couchdb" {
  name                    = "couchdb"
  machine_type            = "e2-micro"
  metadata_startup_script = "${var.cloudflare_pem} > ~/cloudflarepriv.pem && mkdir ~/data && docker run -d --restart always --name couchdb7 -p 443:6984 -v ~/data:/opt/couchdb/data -v ~/cloudflarepriv.pem:/opt/couchdb/etc/cloudflarepriv.pem docker.io/neverlucky135/couchdb:latest"
  boot_disk {
    device_name = "couchdb"
    initialize_params {
      image = "projects/cos-cloud/global/images/cos-stable-105-17412-156-30"
      size  = 30
      type  = "pd-balanced"
    }
  }
  network_interface {
    network = "default"
    access_config {
      network_tier = "PREMIUM"
    }
  }
  scheduling {
    preemptible        = false
    provisioning_model = "STANDARD"
  }
  shielded_instance_config {
    enable_integrity_monitoring = true
    enable_secure_boot          = false
    enable_vtpm                 = true
  }
}
