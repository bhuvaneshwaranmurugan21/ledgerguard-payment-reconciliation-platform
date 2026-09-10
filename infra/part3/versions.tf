terraform {
  required_version = "= 1.13.1"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.11.0"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region              = "ap-southeast-2"
  allowed_account_ids = ["857229544428"]
  default_tags {
    tags = {
      Project   = "LedgerGuard"
      ManagedBy = "Terraform"
      Part      = "3"
    }
  }
}
