terraform {
  required_version = "~> 1.15.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.54.0"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Application = "ProofShape"
      Boundary    = "proofshape-commercial-bootstrap"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}
