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
/*
module "gce-container" {
  source  = "terraform-google-modules/container-vm/google"
  version = "~> 2.0"

  container = {
    image        = "docker.io/neverlucky135/couchdb:latest"
    volumeMounts = [
      {
        mountPath = "/opt/couchdb/etc/cloudflarepriv.pem"
        name      = "cloudflarepriv"
        readOnly  = false
      },
      {
        mountPath = "/opt/couchdb/data"
        name      = "db_dir"
        readOnly  = false
      },
    ]
  }
  volumes = [
    {
      name     = "cloudflarepriv"
      hostPath = {
        path = "/etc/app/cloudflarepriv.pem"
      }
    },
    {
      name     = "db_dir"
      hostPath = {
        path = "/etc/app/data"
      }
    },
  ]
  restart_policy = "Always"
}

resource "google_compute_address" "default" {
  name = "couchdb-ingress"
}

locals {
  COUCHDB_NETWORK_TAG = "couchdb"
}

resource "google_compute_instance" "couchdb" {
  name         = "couchdb"
  machine_type = "e2-micro"
  boot_disk {
    device_name = "couchdb"
    initialize_params {
      image = "projects/cos-cloud/global/images/cos-stable-105-17412-156-30"
      size  = 30
      type  = "pd-standard"
    }
  }
  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.default.address
    }
  }
  tags     = [local.COUCHDB_NETWORK_TAG]
  metadata = {
    gce-container-declaration = module.gce-container.metadata_value
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
  metadata_startup_script = templatefile("${path.module}/startup.sh.tpl", {
    cloudflarepriv = file("/mnt/workspace/cloudflarepriv.pem")
  })
}

resource "google_compute_firewall" "couchdb" {
  name          = local.COUCHDB_NETWORK_TAG
  network       = "default"
  source_ranges = ["0.0.0.0/0"]
  allow {
    protocol = "tcp"
    ports    = ["6984", "5984"]
  }
  target_tags = [local.COUCHDB_NETWORK_TAG]
}
*/