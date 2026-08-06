resource "aws_s3_bucket" "artifacts" {
  bucket        = local.artifact_bucket_name
  force_destroy = var.s3_force_destroy

  tags = {
    Name        = local.artifact_bucket_name
    DataClass   = "customer-derived-cad"
    ReleaseEdge = "cloudfront-only"
  }
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.main.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "multipart-and-version-retention"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = var.s3_abort_incomplete_multipart_days
    }

    dynamic "noncurrent_version_expiration" {
      for_each = var.s3_noncurrent_version_expiration_days == null ? [] : [var.s3_noncurrent_version_expiration_days]

      content {
        noncurrent_days = noncurrent_version_expiration.value
      }
    }
  }

  # Deep health performs a real write/read/list/delete probe. Keep those
  # non-customer canary versions from inheriting evidence retention.
  rule {
    id     = "expire-health-canaries"
    status = "Enabled"

    filter {
      prefix = "${var.environment}/health/.cadverify-health/"
    }

    expiration {
      days = 1
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.artifacts]
}

resource "aws_s3_bucket_cors_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  cors_rule {
    id = "exact-proofshape-release-origins"
    allowed_headers = [
      "content-type",
      "x-amz-content-sha256",
      "x-amz-date",
      "x-amz-security-token",
      "x-amz-server-side-encryption",
      "x-amz-server-side-encryption-aws-kms-key-id",
    ]
    allowed_methods = ["GET", "HEAD", "POST", "PUT"]
    allowed_origins = distinct(concat([local.canonical_public_origin], var.additional_s3_cors_origins))
    expose_headers  = ["etag", "x-amz-version-id"]
    max_age_seconds = 3600
  }
}

# Incoming multipart ZIPs are transient processing inputs, not durable
# evidence. This bucket deliberately never enables versioning so a successful
# DeleteObject makes storage_cleaned_at truthful. Lifecycle is a short backstop
# for abandoned completed objects and incomplete multipart uploads.
resource "aws_s3_bucket" "transient_uploads" {
  bucket        = local.transient_upload_bucket_name
  force_destroy = var.s3_force_destroy

  tags = {
    Name               = local.transient_upload_bucket_name
    DataClass          = "transient-customer-upload"
    VersioningContract = "never-enabled"
  }
}

resource "aws_s3_bucket_ownership_controls" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.main.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id

  rule {
    id     = "expire-transient-incoming-uploads"
    status = "Enabled"

    filter {}

    expiration {
      days = var.transient_upload_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id

  cors_rule {
    id = "exact-proofshape-direct-upload-origins"
    allowed_headers = [
      "content-type",
      "x-amz-content-sha256",
      "x-amz-date",
      "x-amz-security-token",
      "x-amz-server-side-encryption",
      "x-amz-server-side-encryption-aws-kms-key-id",
    ]
    allowed_methods = ["GET", "HEAD", "POST", "PUT"]
    allowed_origins = distinct(concat([local.canonical_public_origin], var.additional_s3_cors_origins))
    expose_headers  = ["etag"]
    max_age_seconds = 900
  }
}

data "aws_iam_policy_document" "artifact_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyOldTls"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }

    condition {
      test     = "Bool"
      variable = "aws:PrincipalIsAWSService"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyWrongExplicitEncryption"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyWrongExplicitKmsKey"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.main.arn]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.artifact_bucket.json
}

data "aws_iam_policy_document" "transient_upload_bucket" {
  # Versioning must never be enabled here: an ordinary DeleteObject must leave
  # no addressable noncurrent copy of transient customer bytes. Enabling it
  # requires an explicit Terraform policy change and review first.
  statement {
    sid    = "DenyVersioningEnablement"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutBucketVersioning"]
    resources = [aws_s3_bucket.transient_uploads.arn]
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.transient_uploads.arn,
      "${aws_s3_bucket.transient_uploads.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyOldTls"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.transient_uploads.arn,
      "${aws_s3_bucket.transient_uploads.arn}/*",
    ]

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }

    condition {
      test     = "Bool"
      variable = "aws:PrincipalIsAWSService"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyWrongExplicitEncryption"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.transient_uploads.arn}/*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyWrongExplicitKmsKey"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.transient_uploads.arn}/*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.main.arn]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "transient_uploads" {
  bucket = aws_s3_bucket.transient_uploads.id
  policy = data.aws_iam_policy_document.transient_upload_bucket.json
}

resource "aws_ecr_repository" "backend" {
  name                 = "${var.project_name}/${var.environment}/backend"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.ecr_force_delete

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${var.project_name}/${var.environment}/frontend"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.ecr_force_delete

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "repositories" {
  for_each = {
    backend  = aws_ecr_repository.backend.name
    frontend = aws_ecr_repository.frontend.name
  }

  repository = each.value
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain the newest ${var.ecr_max_image_count} immutable release images for bounded rollback"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["release-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_max_image_count
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Bound abandoned untagged image storage"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = max(5, ceil(var.ecr_max_image_count / 4))
        }
        action = {
          type = "expire"
        }
      },
    ]
  })
}

resource "aws_secretsmanager_secret" "runtime" {
  for_each = setsubtract(local.runtime_secret_names, toset(keys(var.runtime_secret_arns)))

  name                    = "/${var.project_name}/${var.environment}/${lower(each.value)}"
  description             = "Metadata-only placeholder for ${each.value}; values are never managed by Terraform"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.runtime_secret_recovery_window_days

  tags = {
    RuntimeEnvironmentVariable = each.value
    ValueManagedBy             = "OperatorOutsideTerraform"
  }
}

# ElastiCache's provider resource still has only a state-persisted auth_token
# argument. Keep the token in Secrets Manager and configure AUTH with the
# out-of-band helper instead; this resource intentionally has no secret value.
resource "aws_secretsmanager_secret" "cache_auth_token" {
  count = var.cache_auth_token_secret_arn == "" ? 1 : 0

  name                    = "/${var.project_name}/${var.environment}/cache-auth-token"
  description             = "ElastiCache AUTH token; value is created and read only outside Terraform"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.runtime_secret_recovery_window_days

  tags = {
    Purpose        = "elasticache-auth"
    ValueManagedBy = "OperatorOutsideTerraform"
  }
}

locals {
  managed_runtime_secret_arns = {
    for name, secret in aws_secretsmanager_secret.runtime : name => secret.arn
  }
  runtime_secret_arns = merge(local.managed_runtime_secret_arns, var.runtime_secret_arns)
  cache_auth_token_secret_arn = (
    var.cache_auth_token_secret_arn != "" ?
    var.cache_auth_token_secret_arn :
    aws_secretsmanager_secret.cache_auth_token[0].arn
  )
}
