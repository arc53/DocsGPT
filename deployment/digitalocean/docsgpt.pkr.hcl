# The DocsGPT 1-Click App for the DigitalOcean Marketplace: an Ubuntu 24.04 snapshot with
# Docker, the docsgpt command and the stack's images already in place. Nothing is
# configured at build time: each Droplet sets itself up on its first boot
# (files/var/lib/cloud/scripts/per-instance/001_onboot), with its own secrets.
#
#   packer init deployment/digitalocean
#   DIGITALOCEAN_TOKEN=... packer build -var docsgpt_version=1.0.0 deployment/digitalocean
#
# See deployment/digitalocean/README.md for testing a build and submitting it.

packer {
  required_plugins {
    digitalocean = {
      source  = "github.com/digitalocean/digitalocean"
      version = "~> 1.4"
    }
  }
}

variable "docsgpt_version" {
  type        = string
  description = "The docsgpt release the image runs: its PyPI package and its Docker images."
}

variable "docsgpt_package" {
  type        = string
  default     = ""
  description = "A local docsgpt wheel to install instead of the PyPI release (to test a branch). Its version must be docsgpt_version."
}

variable "image_tag" {
  type        = string
  default     = ""
  description = "Docker image tag to pre-pull (default: docsgpt_version)."
}

variable "region" {
  type    = string
  default = "nyc3"
}

# The build Droplet's disk becomes the image's minimum disk, so this is also the smallest
# plan the image can run on: 4 GB of memory and an 80 GB disk.
variable "size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "snapshot_name" {
  type    = string
  default = ""
}

locals {
  timestamp     = formatdate("YYYYMMDD-hhmmss", timestamp())
  image_tag     = var.image_tag != "" ? var.image_tag : var.docsgpt_version
  snapshot_name = var.snapshot_name != "" ? var.snapshot_name : "docsgpt-${var.docsgpt_version}-${local.timestamp}"
  # DigitalOcean's cleanup and image check, pinned to a commit and checked against these hashes.
  partners_commit = "b70878804ca27c01d5f5e882d26485defbaba210"
  partners_base   = "https://raw.githubusercontent.com/digitalocean/marketplace-partners/${local.partners_commit}/scripts"
}

source "digitalocean" "docsgpt" {
  # api_token comes from DIGITALOCEAN_TOKEN (or DIGITALOCEAN_ACCESS_TOKEN) in the environment.
  image         = "ubuntu-24-04-x64"
  region        = var.region
  size          = var.size
  ssh_username  = "root"
  snapshot_name = local.snapshot_name
  tags          = ["docsgpt-image-build"]
}

build {
  sources = ["source.digitalocean.docsgpt"]

  provisioner "shell" {
    # Exit status 2 means cloud-init finished with recoverable errors, which Ubuntu 24.04
    # reports on a clean boot too.
    inline = ["cloud-init status --wait || [ $? -eq 2 ]"]
  }

  provisioner "file" {
    source      = "${path.root}/files/"
    destination = "/"
  }

  provisioner "file" {
    # Uploaded even when empty, so the next step has one path to look at.
    source      = var.docsgpt_package != "" ? var.docsgpt_package : "${path.root}/README.md"
    destination = "/root/docsgpt-package"
  }

  provisioner "shell" {
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
      "DOCSGPT_VERSION=${var.docsgpt_version}",
      "DOCSGPT_IMAGE_TAG=${local.image_tag}",
      "DOCSGPT_FROM_WHEEL=${var.docsgpt_package != "" ? basename(var.docsgpt_package) : ""}",
    ]
    scripts = [
      "${path.root}/scripts/10-system.sh",
      "${path.root}/scripts/20-docsgpt.sh",
    ]
  }

  provisioner "shell" {
    environment_vars = ["DEBIAN_FRONTEND=noninteractive"]
    inline = [
      "set -e",
      "cd /root",
      "curl -fsSL --retry 3 -o 90-cleanup.sh ${local.partners_base}/90-cleanup.sh",
      "curl -fsSL --retry 3 -o 99-img-check.sh ${local.partners_base}/99-img-check.sh",
      "printf '%s  %s\\n' 5e2fe7ce30892a26ed2731238d9f26c40ae8b1084b070ce095f3b99ab1a2cc81 90-cleanup.sh 91ff2b1880439c97ccdc49554c5ed8901b89ef250c8ac5fffe52811c68abac49 99-img-check.sh | sha256sum -c -",
      "bash 90-cleanup.sh",
      "bash 99-img-check.sh",
      "rm -f 90-cleanup.sh 99-img-check.sh",
    ]
  }

  post-processor "manifest" {
    output     = "${path.root}/packer-manifest.json"
    strip_path = true
    custom_data = {
      docsgpt_version = var.docsgpt_version
      image_tag       = local.image_tag
    }
  }
}
