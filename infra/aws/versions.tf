terraform {
  required_version = "~> 1.15.8"

  backend "s3" {}

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
    tags = local.tags
  }
}

# CloudFront-scoped WAF resources must be managed through us-east-1 even when
# the regional application stack lives elsewhere.
provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = local.tags
  }
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_availability_zone" "selected" {
  for_each = toset(local.selected_availability_zones)

  name = each.value
}
