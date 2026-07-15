output "backend_config" {
  description = "Values for an environment .backend.hcl file. Use a distinct key per isolated stack."
  value = {
    bucket       = aws_s3_bucket.state.id
    encrypt      = true
    kms_key_id   = aws_kms_key.state.arn
    region       = var.aws_region
    use_lockfile = true
  }
}

output "state_bucket_arn" {
  value = aws_s3_bucket.state.arn
}

output "state_kms_key_arn" {
  value = aws_kms_key.state.arn
}
