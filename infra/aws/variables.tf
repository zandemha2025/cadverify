variable "aws_region" {
  description = "Commercial AWS region for the regional application stack."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region)) && !can(regex("-gov-", var.aws_region))
    error_message = "aws_region must be a commercial AWS region, not GovCloud."
  }
}

variable "aws_account_id" {
  description = "Exact 12-digit AWS account allowed for this isolated stack."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "project_name" {
  description = "Stable commercial-plane resource prefix. Do not reuse an Arcus or regulated-plane prefix."
  type        = string
  default     = "proofshape-commercial"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name)) && !can(regex("arcus", lower(var.project_name)))
    error_message = "project_name must be a lowercase AWS-safe name and must not cross the Arcus boundary."
  }
}

variable "environment" {
  description = "Isolated infrastructure environment."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "application_environment" {
  description = "ProofShape runtime environment understood by existing fail-closed application guards."
  type        = string

  validation {
    condition     = contains(["saas-staging", "saas-production"], var.application_environment)
    error_message = "application_environment must be saas-staging or saas-production."
  }
}

variable "availability_profile" {
  description = "Honest operator declaration: bootstrap permits single-copy services; ha enforces redundant service/data settings."
  type        = string
  default     = "bootstrap"

  validation {
    condition     = contains(["bootstrap", "ha"], var.availability_profile)
    error_message = "availability_profile must be bootstrap or ha."
  }
}

variable "tags" {
  description = "Additional non-secret tags."
  type        = map(string)
  default     = {}
}

variable "availability_zones" {
  description = "Exactly two AZs. Leave empty to select the first two available AZs in the region."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.availability_zones) == 0 || (length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2)
    error_message = "availability_zones must be empty or contain exactly two distinct AZs."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the environment VPC."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 2))
    error_message = "vpc_cidr must be a valid IPv4 CIDR."
  }
}

variable "public_subnet_cidrs" {
  description = "Two public subnet CIDRs used only by tightly scoped public-IP Fargate tasks."
  type        = list(string)
  default     = ["10.40.0.0/24", "10.40.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2 && alltrue([for cidr in var.public_subnet_cidrs : can(cidrhost(cidr, 2))])
    error_message = "public_subnet_cidrs must contain exactly two valid IPv4 CIDRs."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private, no-default-route subnet CIDRs for RDS and ElastiCache."
  type        = list(string)
  default     = ["10.40.10.0/24", "10.40.11.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == 2 && alltrue([for cidr in var.private_subnet_cidrs : can(cidrhost(cidr, 2))])
    error_message = "private_subnet_cidrs must contain exactly two valid IPv4 CIDRs."
  }
}

variable "enable_vpc_flow_logs" {
  description = "Write VPC flow logs to an encrypted CloudWatch log group."
  type        = bool
  default     = true
}

variable "alb_deletion_protection" {
  description = "Protect the private CloudFront VPC-origin ALB from deletion."
  type        = bool
  default     = false
}

variable "alb_access_log_bucket_name" {
  description = "Optional pre-created S3 bucket name for private ALB access logs. Production/HA requires it and the matching ELB log-delivery bucket policy."
  type        = string
  default     = ""

  validation {
    condition     = var.alb_access_log_bucket_name == "" || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.alb_access_log_bucket_name))
    error_message = "alb_access_log_bucket_name must be empty or a valid lowercase S3 bucket name."
  }
}

variable "cloudfront_origin_protocol_policy" {
  description = "CloudFront VPC-origin transport. http-only supports the default CloudFront hostname for staging; production/HA requires https-only."
  type        = string
  default     = "http-only"

  validation {
    condition     = contains(["http-only", "https-only"], var.cloudfront_origin_protocol_policy)
    error_message = "cloudfront_origin_protocol_policy must be http-only or https-only."
  }
}

variable "alb_origin_acm_certificate_arn" {
  description = "Regional ACM certificate ARN for the private ALB HTTPS listener. Required for https-only origin transport."
  type        = string
  default     = ""
}

variable "cloudfront_alias" {
  description = "Optional custom DNS alias. Empty uses the working CloudFront distribution hostname."
  type        = string
  default     = ""

  validation {
    condition     = var.cloudfront_alias == "" || can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.cloudfront_alias))
    error_message = "cloudfront_alias must be empty or a lowercase DNS hostname without scheme or path."
  }
}

variable "cloudfront_acm_certificate_arn" {
  description = "Optional us-east-1 ACM certificate ARN required when cloudfront_alias is set."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Optional Route53 hosted zone ID in which to create A/AAAA aliases for cloudfront_alias."
  type        = string
  default     = ""
}

variable "cloudfront_price_class" {
  description = "CloudFront price class. PriceClass_100 is the budget-aware bootstrap default."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.cloudfront_price_class)
    error_message = "cloudfront_price_class must be PriceClass_100, PriceClass_200, or PriceClass_All."
  }
}

variable "cloudfront_ipv6_enabled" {
  description = "Enable IPv6 at the CloudFront viewer edge."
  type        = bool
  default     = true
}

variable "cloudfront_wait_for_deployment" {
  description = "Wait for CloudFront propagation during Terraform apply."
  type        = bool
  default     = true
}

variable "cloudfront_retain_on_delete" {
  description = "Disable the CloudFront distribution instead of deleting it when removed from Terraform. Required for production/HA."
  type        = bool
  default     = false
}

variable "enable_static_asset_caching" {
  description = "Cache immutable /_next/static assets; all dynamic/default traffic remains uncached."
  type        = bool
  default     = true
}

variable "cloudfront_access_log_bucket_domain" {
  description = "Optional pre-created S3 logging bucket domain name. Empty disables CloudFront standard access logs."
  type        = string
  default     = ""

  validation {
    condition = (
      var.cloudfront_access_log_bucket_domain == "" ||
      can(regex("^[a-z0-9][a-z0-9.-]+\\.s3(?:\\.[a-z0-9-]+)?\\.amazonaws\\.com$", var.cloudfront_access_log_bucket_domain))
    )
    error_message = "cloudfront_access_log_bucket_domain must be empty or an S3 bucket domain name without a scheme/path."
  }
}

variable "enable_waf" {
  description = "Attach a CloudFront-scoped WAF with AWS managed baseline rules and rate limiting."
  type        = bool
  default     = false
}

variable "enable_waf_logging" {
  description = "Write WAF records to a retained CloudWatch log group in us-east-1."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "Five-minute per-IP CloudFront request ceiling for the WAF rate rule."
  type        = number
  default     = 2000

  validation {
    condition     = var.waf_rate_limit >= 100
    error_message = "waf_rate_limit must be at least 100."
  }
}

variable "artifact_bucket_name" {
  description = "Optional globally unique durable evidence bucket name. Empty derives an account/region/environment name."
  type        = string
  default     = ""

  validation {
    condition     = var.artifact_bucket_name == "" || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.artifact_bucket_name))
    error_message = "artifact_bucket_name must be empty or a valid lowercase S3 bucket name."
  }
}

variable "transient_upload_bucket_name" {
  description = "Optional globally unique unversioned incoming-upload bucket name. Empty derives an isolated account/region/environment name."
  type        = string
  default     = ""

  validation {
    condition     = var.transient_upload_bucket_name == "" || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.transient_upload_bucket_name))
    error_message = "transient_upload_bucket_name must be empty or a valid lowercase S3 bucket name."
  }
}

variable "transient_upload_expiration_days" {
  description = "Days before completed but uncleaned incoming uploads become eligible for asynchronous S3 lifecycle expiration. Must stay short and exceed the application's active upload TTL."
  type        = number
  default     = 2

  validation {
    condition     = var.transient_upload_expiration_days >= 1 && var.transient_upload_expiration_days <= 7
    error_message = "transient_upload_expiration_days must be between 1 and 7."
  }
}

variable "transient_upload_contract_confirmed" {
  description = "Operator attestation that the release image routes direct-uploads through DIRECT_UPLOAD_S3_* and never stores transient incoming bytes in the durable versioned bucket. Required before services start."
  type        = bool
  default     = false
}

variable "s3_force_destroy" {
  description = "Permit Terraform to delete non-empty customer-object storage. Keep false for production."
  type        = bool
  default     = false
}

variable "s3_abort_incomplete_multipart_days" {
  description = "Days before incomplete multipart uploads are aborted."
  type        = number
  default     = 7

  validation {
    condition     = var.s3_abort_incomplete_multipart_days >= 1
    error_message = "s3_abort_incomplete_multipart_days must be at least 1."
  }
}

variable "s3_noncurrent_version_expiration_days" {
  description = "Durable evidence noncurrent-version retention. Null preserves evidence versions indefinitely."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.s3_noncurrent_version_expiration_days == null || var.s3_noncurrent_version_expiration_days >= 30
    error_message = "s3_noncurrent_version_expiration_days must be null or at least 30."
  }
}

variable "additional_s3_cors_origins" {
  description = "Additional exact HTTPS origins; wildcards are rejected. The canonical CloudFront origin is always included."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for origin in var.additional_s3_cors_origins :
      can(regex("^https://[A-Za-z0-9.-]+(?::[0-9]+)?$", origin)) && !strcontains(origin, "*")
    ])
    error_message = "Every additional S3 CORS origin must be an exact HTTPS origin with no wildcard or path."
  }
}

variable "kms_deletion_window_days" {
  description = "KMS deletion waiting period."
  type        = number
  default     = 30

  validation {
    condition     = var.kms_deletion_window_days >= 7 && var.kms_deletion_window_days <= 30
    error_message = "kms_deletion_window_days must be between 7 and 30."
  }
}

variable "ecr_force_delete" {
  description = "Permit deletion of ECR repositories that still contain images."
  type        = bool
  default     = false
}

variable "ecr_max_image_count" {
  description = "Maximum immutable release images retained per repository for bounded rollback; abandoned untagged images have a smaller derived cap."
  type        = number
  default     = 100

  validation {
    condition     = var.ecr_max_image_count >= 10
    error_message = "ecr_max_image_count must be at least 10."
  }
}

variable "rds_engine_version" {
  description = "PostgreSQL engine major/minor selector."
  type        = string
  default     = "16"
}

variable "rds_parameter_group_family" {
  description = "RDS parameter group family matching rds_engine_version."
  type        = string
  default     = "postgres16"
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_database_name" {
  description = "Initial PostgreSQL database."
  type        = string
  default     = "proofshape"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{0,62}$", var.rds_database_name))
    error_message = "rds_database_name must be a valid PostgreSQL identifier."
  }
}

variable "rds_master_username" {
  description = "RDS bootstrap administrator name. RDS generates and manages its password outside Terraform state."
  type        = string
  default     = "proofshape_admin"
}

variable "rds_port" {
  description = "PostgreSQL port."
  type        = number
  default     = 5432
}

variable "rds_allocated_storage_gib" {
  description = "Initial gp3 storage in GiB."
  type        = number
  default     = 30
}

variable "rds_max_allocated_storage_gib" {
  description = "Storage autoscaling ceiling in GiB."
  type        = number
  default     = 200
}

variable "rds_multi_az" {
  description = "Standby RDS instance in another AZ. False is a real bootstrap availability reduction."
  type        = bool
  default     = false
}

variable "rds_backup_retention_days" {
  description = "Automated backup/PITR retention in days."
  type        = number
  default     = 7

  validation {
    condition     = var.rds_backup_retention_days >= 1 && var.rds_backup_retention_days <= 35
    error_message = "rds_backup_retention_days must be between 1 and 35."
  }
}

variable "rds_deletion_protection" {
  description = "Enable RDS deletion protection."
  type        = bool
  default     = false
}

variable "rds_skip_final_snapshot" {
  description = "Skip the final RDS snapshot on destroy. Keep false for production."
  type        = bool
  default     = true
}

variable "rds_delete_automated_backups" {
  description = "Delete automated backups with the DB instance. Keep false for production recovery."
  type        = bool
  default     = true
}

variable "rds_performance_insights_enabled" {
  description = "Enable encrypted RDS Performance Insights."
  type        = bool
  default     = false
}

variable "rds_performance_insights_retention_days" {
  description = "Performance Insights retention (7 or 731 days)."
  type        = number
  default     = 7

  validation {
    condition     = contains([7, 731], var.rds_performance_insights_retention_days)
    error_message = "rds_performance_insights_retention_days must be 7 or 731."
  }
}

variable "rds_apply_immediately" {
  description = "Apply RDS modifications immediately instead of the maintenance window."
  type        = bool
  default     = false
}

variable "cache_engine_version" {
  description = "Redis OSS engine version."
  type        = string
  default     = "7.1"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "cache_node_count" {
  description = "Cache replicas including primary. One node has no automatic failover."
  type        = number
  default     = 1

  validation {
    condition     = var.cache_node_count >= 1 && var.cache_node_count <= 6
    error_message = "cache_node_count must be between 1 and 6."
  }
}

variable "cache_snapshot_retention_days" {
  description = "ElastiCache snapshot retention in days."
  type        = number
  default     = 1

  validation {
    condition     = var.cache_snapshot_retention_days >= 0 && var.cache_snapshot_retention_days <= 35
    error_message = "cache_snapshot_retention_days must be between 0 and 35."
  }
}

variable "cache_final_snapshot_identifier" {
  description = "Optional final cache snapshot name. Empty skips a final cache snapshot."
  type        = string
  default     = ""
}

variable "cache_apply_immediately" {
  description = "Apply ElastiCache modifications immediately."
  type        = bool
  default     = false
}

variable "cache_auth_token_secret_arn" {
  description = "Optional externally managed Secrets Manager ARN containing the ElastiCache AUTH token. Empty creates metadata only; Terraform never reads or writes its value."
  type        = string
  default     = ""

  validation {
    condition = (
      var.cache_auth_token_secret_arn == "" ||
      can(regex("^arn:[^:]+:secretsmanager:[^:]+:[0-9]{12}:secret:.+$", var.cache_auth_token_secret_arn))
    )
    error_message = "cache_auth_token_secret_arn must be empty or a full Secrets Manager ARN."
  }
}

variable "cache_authentication_confirmed" {
  description = "Operator attestation that aws-enable-cache-auth.sh completed and the REDIS_URL secret carries the same AUTH token. Required before API/worker services can start."
  type        = bool
  default     = false
}

variable "runtime_secret_arns" {
  description = "Optional externally managed Secrets Manager ARNs keyed by expected environment variable; missing keys get metadata-only placeholders."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for name, arn in var.runtime_secret_arns :
      can(regex("^[A-Z][A-Z0-9_]+$", name)) && can(regex("^arn:[^:]+:secretsmanager:[^:]+:[0-9]{12}:secret:.+$", arn))
    ])
    error_message = "runtime_secret_arns must map uppercase environment names to full Secrets Manager ARNs."
  }
}

variable "external_secret_kms_key_arns" {
  description = "Customer-managed KMS key ARNs required to decrypt externally supplied runtime secrets."
  type        = list(string)
  default     = []
}

variable "runtime_secret_recovery_window_days" {
  description = "Recovery window for metadata-only runtime secret placeholders."
  type        = number
  default     = 30

  validation {
    condition     = var.runtime_secret_recovery_window_days >= 7 && var.runtime_secret_recovery_window_days <= 30
    error_message = "runtime_secret_recovery_window_days must be between 7 and 30."
  }
}

variable "enable_workloads" {
  description = "Create digest-pinned ECS task definitions. Requires images and populated secret versions operationally."
  type        = bool
  default     = false
}

variable "enable_services" {
  description = "Create long-running frontend/API/worker ECS services. enable_workloads must also be true."
  type        = bool
  default     = false
}

variable "backend_image" {
  description = "Initial backend ECR image URI qualified by @sha256 digest."
  type        = string
  default     = ""

  validation {
    condition     = var.backend_image == "" || can(regex("^[^[:space:]]+@sha256:[0-9a-f]{64}$", var.backend_image))
    error_message = "backend_image must be empty or an @sha256-qualified image URI."
  }
}

variable "frontend_image" {
  description = "Initial frontend ECR image URI qualified by @sha256 digest."
  type        = string
  default     = ""

  validation {
    condition     = var.frontend_image == "" || can(regex("^[^[:space:]]+@sha256:[0-9a-f]{64}$", var.frontend_image))
    error_message = "frontend_image must be empty or an @sha256-qualified image URI."
  }
}

variable "initial_release_id" {
  description = "Exact lowercase 40-character release SHA placed in initial task definitions. Required when workloads are enabled."
  type        = string
  default     = "bootstrap"
}

variable "fargate_platform_version" {
  description = "Explicit ECS Fargate Linux platform version used by services and one-shot migrations."
  type        = string
  default     = "1.4.0"
}

variable "api_capacity_provider" {
  description = "Capacity provider for the API service. Production/HA must use FARGATE."
  type        = string
  default     = "FARGATE"

  validation {
    condition     = contains(["FARGATE", "FARGATE_SPOT"], var.api_capacity_provider)
    error_message = "api_capacity_provider must be FARGATE or FARGATE_SPOT."
  }
}

variable "worker_capacity_provider" {
  description = "Capacity provider for the durable/idempotent worker service. Budget staging may use FARGATE_SPOT."
  type        = string
  default     = "FARGATE"

  validation {
    condition     = contains(["FARGATE", "FARGATE_SPOT"], var.worker_capacity_provider)
    error_message = "worker_capacity_provider must be FARGATE or FARGATE_SPOT."
  }
}

variable "frontend_capacity_provider" {
  description = "Capacity provider for the frontend service. Production/HA must use FARGATE."
  type        = string
  default     = "FARGATE"

  validation {
    condition     = contains(["FARGATE", "FARGATE_SPOT"], var.frontend_capacity_provider)
    error_message = "frontend_capacity_provider must be FARGATE or FARGATE_SPOT."
  }
}

variable "api_cpu" {
  type        = number
  description = "API task CPU units."
  default     = 2048
}

variable "api_memory" {
  type        = number
  description = "API task memory in MiB."
  default     = 4096
}

variable "worker_cpu" {
  type        = number
  description = "Worker task CPU units."
  default     = 2048
}

variable "worker_memory" {
  type        = number
  description = "Worker task memory in MiB."
  default     = 4096
}

variable "frontend_cpu" {
  type        = number
  description = "Frontend task CPU units."
  default     = 512
}

variable "frontend_memory" {
  type        = number
  description = "Frontend task memory in MiB."
  default     = 1024
}

variable "migration_cpu" {
  type        = number
  description = "Migration task CPU units."
  default     = 512
}

variable "migration_memory" {
  type        = number
  description = "Migration task memory in MiB."
  default     = 1024
}

variable "batch_default_concurrency" {
  description = "Default number of concurrently processed CAD batch parts per worker; bounded to protect task memory."
  type        = number
  default     = 4

  validation {
    condition     = floor(var.batch_default_concurrency) == var.batch_default_concurrency && var.batch_default_concurrency >= 1 && var.batch_default_concurrency <= 8
    error_message = "batch_default_concurrency must be an integer from 1 through 8."
  }
}

variable "backend_ephemeral_storage_gib" {
  description = "API/worker scratch storage for bounded CAD processing."
  type        = number
  default     = 40

  validation {
    condition     = var.backend_ephemeral_storage_gib >= 21 && var.backend_ephemeral_storage_gib <= 200
    error_message = "backend_ephemeral_storage_gib must be between 21 and 200."
  }
}

variable "api_desired_count" {
  type        = number
  description = "Initial API service task count."
  default     = 1

  validation {
    condition     = floor(var.api_desired_count) == var.api_desired_count && var.api_desired_count >= 0
    error_message = "api_desired_count must be a non-negative integer."
  }
}

variable "worker_desired_count" {
  type        = number
  description = "Initial worker service task count."
  default     = 1

  validation {
    condition     = floor(var.worker_desired_count) == var.worker_desired_count && var.worker_desired_count >= 0
    error_message = "worker_desired_count must be a non-negative integer."
  }
}

variable "frontend_desired_count" {
  type        = number
  description = "Initial frontend service task count."
  default     = 1

  validation {
    condition     = floor(var.frontend_desired_count) == var.frontend_desired_count && var.frontend_desired_count >= 0
    error_message = "frontend_desired_count must be a non-negative integer."
  }
}

variable "deployment_minimum_healthy_percent" {
  type        = number
  description = "ECS rolling deployment minimum healthy percentage."
  default     = 100

  validation {
    condition     = var.deployment_minimum_healthy_percent >= 0 && var.deployment_minimum_healthy_percent <= 100
    error_message = "deployment_minimum_healthy_percent must be from 0 through 100."
  }
}

variable "deployment_maximum_percent" {
  type        = number
  description = "ECS rolling deployment maximum percentage."
  default     = 200

  validation {
    condition     = var.deployment_maximum_percent >= 100 && var.deployment_maximum_percent <= 200
    error_message = "deployment_maximum_percent must be from 100 through 200."
  }
}

variable "enable_autoscaling" {
  description = "Enable CPU and memory target tracking for all long-running ECS services."
  type        = bool
  default     = false
}

variable "api_autoscaling_min" {
  type        = number
  default     = 1
  description = "API autoscaling floor."
}

variable "api_autoscaling_max" {
  type        = number
  default     = 4
  description = "API autoscaling ceiling."
}

variable "worker_autoscaling_min" {
  type        = number
  default     = 1
  description = "Worker autoscaling floor."
}

variable "worker_autoscaling_max" {
  type        = number
  default     = 4
  description = "Worker autoscaling ceiling."
}

variable "frontend_autoscaling_min" {
  type        = number
  default     = 1
  description = "Frontend autoscaling floor."
}

variable "frontend_autoscaling_max" {
  type        = number
  default     = 4
  description = "Frontend autoscaling ceiling."
}

variable "autoscaling_cpu_target" {
  type        = number
  description = "ECS average CPU target percentage."
  default     = 65

  validation {
    condition     = var.autoscaling_cpu_target >= 1 && var.autoscaling_cpu_target <= 100
    error_message = "autoscaling_cpu_target must be from 1 through 100."
  }
}

variable "autoscaling_memory_target" {
  type        = number
  description = "ECS average memory target percentage."
  default     = 75

  validation {
    condition     = var.autoscaling_memory_target >= 1 && var.autoscaling_memory_target <= 100
    error_message = "autoscaling_memory_target must be from 1 through 100."
  }
}

variable "api_environment" {
  description = "Additional non-secret API environment variables. Secure baseline keys cannot be overridden."
  type        = map(string)
  default     = {}
}

variable "worker_environment" {
  description = "Additional non-secret worker environment variables. Secure baseline keys cannot be overridden."
  type        = map(string)
  default     = {}
}

variable "frontend_environment" {
  description = "Additional non-secret frontend environment variables. Secure baseline keys cannot be overridden."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch application/data-service log retention."
  type        = number
  default     = 30

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731,
      1096, 1827, 2192, 2557, 2922, 3288, 3653,
    ], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch Logs-supported retention value."
  }
}

variable "enable_container_insights" {
  description = "Enable ECS Container Insights."
  type        = bool
  default     = false
}

variable "enable_alarms" {
  description = "Create baseline ALB, ECS, RDS, and ElastiCache CloudWatch alarms."
  type        = bool
  default     = false
}

variable "create_alarm_topic" {
  description = "Create an encrypted SNS topic and include it in alarm actions."
  type        = bool
  default     = true
}

variable "alarm_action_arns" {
  description = "Additional SNS or incident action ARNs for alarms."
  type        = list(string)
  default     = []
}

variable "enable_budget" {
  description = "Create a monthly AWS cost budget."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "Monthly budget amount in USD."
  type        = number
  default     = 250

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "budget_alert_emails" {
  description = "Email recipients for forecasted 80%, actual 80%, and actual 100% account-wide budget notices."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for email in var.budget_alert_emails : can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", email))
    ])
    error_message = "budget_alert_emails must contain syntactically valid email addresses."
  }
}

variable "enable_github_oidc" {
  description = "Create the environment-scoped GitHub deployment role."
  type        = bool
  default     = true
}

variable "create_github_oidc_provider" {
  description = "Create the account-global GitHub OIDC provider. Set false when the account already has one."
  type        = bool
  default     = false
}

variable "github_oidc_provider_arn" {
  description = "Existing account GitHub OIDC provider ARN when create_github_oidc_provider is false."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "Exact owner/repository allowed to assume the deployment role."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be empty or owner/repository."
  }
}

variable "github_environment" {
  description = "Exact protected GitHub environment encoded into the OIDC subject."
  type        = string
  default     = ""
}

variable "github_oidc_max_session_seconds" {
  description = "Maximum deployment-role session length."
  type        = number
  default     = 3600

  validation {
    condition     = var.github_oidc_max_session_seconds >= 900 && var.github_oidc_max_session_seconds <= 43200
    error_message = "github_oidc_max_session_seconds must be between 900 and 43200."
  }
}
