variable "aws_region" {
  description = "Commercial AWS region for Terraform state."
  type        = string
}

variable "aws_account_id" {
  description = "Exact 12-digit account that will own state."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid S3 bucket name."
  }
}

variable "noncurrent_state_retention_days" {
  description = "Retention for noncurrent state object versions."
  type        = number
  default     = 365

  validation {
    condition     = var.noncurrent_state_retention_days >= 90
    error_message = "Retain noncurrent state versions for at least 90 days."
  }
}

variable "kms_deletion_window_days" {
  description = "KMS deletion waiting period."
  type        = number
  default     = 30
}
