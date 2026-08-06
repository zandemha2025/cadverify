locals {
  # Preserve the environment suffix when a long project name is supplied. A
  # simple truncation can otherwise make staging and production collide.
  name = "${substr(var.project_name, 0, min(length(var.project_name), 31 - length(var.environment)))}-${var.environment}"

  direct_upload_public_origin = "https://${aws_s3_bucket.transient_uploads.id}.s3.${var.aws_region}.${data.aws_partition.current.dns_suffix}"

  fargate_valid_memory = {
    "256"   = toset([512, 1024, 2048])
    "512"   = toset([1024, 2048, 3072, 4096])
    "1024"  = toset(range(2048, 8193, 1024))
    "2048"  = toset(range(4096, 16385, 1024))
    "4096"  = toset(range(8192, 30721, 1024))
    "8192"  = toset(range(16384, 61441, 4096))
    "16384" = toset(range(32768, 122881, 8192))
  }

  cloudfront_vpc_origin_supported_regions = toset([
    "af-south-1",
    "ap-east-1",
    "ap-east-2",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-south-1",
    "ap-south-2",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-southeast-3",
    "ap-southeast-4",
    "ap-southeast-5",
    "ap-southeast-6",
    "ap-southeast-7",
    "ca-central-1",
    "ca-west-1",
    "eu-central-1",
    "eu-central-2",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "il-central-1",
    "me-central-1",
    "me-south-1",
    "mx-central-1",
    "sa-east-1",
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
  ])
  cloudfront_vpc_origin_unsupported_zone_ids = lookup({
    ap-northeast-1 = ["apne1-az3"]
    ca-central-1   = ["cac1-az3"]
    us-east-1      = ["use1-az3"]
    us-west-1      = ["usw1-az2"]
  }, var.aws_region, [])
  cloudfront_vpc_origin_eligible_zones = [
    for index, name in data.aws_availability_zones.available.names : name
    if !contains(
      local.cloudfront_vpc_origin_unsupported_zone_ids,
      data.aws_availability_zones.available.zone_ids[index],
    )
  ]
  selected_availability_zones = (
    length(var.availability_zones) == 2 ?
    var.availability_zones :
    slice(local.cloudfront_vpc_origin_eligible_zones, 0, 2)
  )

  tags = merge(var.tags, {
    Application = "ProofShape"
    Boundary    = "proofshape-commercial"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Project     = var.project_name
  })

  artifact_bucket_suffix = "${var.aws_account_id}-${var.aws_region}-objects"
  upload_bucket_suffix   = "${var.aws_account_id}-${var.aws_region}-uploads"
  artifact_bucket_name = var.artifact_bucket_name != "" ? var.artifact_bucket_name : format(
    "%s-%s",
    substr(local.name, 0, min(length(local.name), 62 - length(local.artifact_bucket_suffix))),
    local.artifact_bucket_suffix,
  )
  transient_upload_bucket_name = (
    var.transient_upload_bucket_name != "" ?
    var.transient_upload_bucket_name :
    format(
      "%s-%s",
      substr(local.name, 0, min(length(local.name), 62 - length(local.upload_bucket_suffix))),
      local.upload_bucket_suffix,
    )
  )

  backend_secret_names = toset([
    "API_KEY_PEPPER",
    "AUTH_PROXY_SECRET",
    "CONNECTOR_FINGERPRINT_KEY",
    "CONNECTOR_SECRET_KEY",
    "DASHBOARD_SESSION_SECRET",
    "DATABASE_URL",
    "DATABASE_URL_DIRECT",
    "DEEP_HEALTH_TOKEN",
    "MAGIC_LINK_SECRET",
    "REDIS_URL",
    "RESEND_API_KEY",
    "RESEND_FROM",
    "SENTRY_DSN",
    "SESSION_SECRET",
    "TURNSTILE_SECRET",
  ])
  frontend_secret_names  = toset(["AUTH_PROXY_SECRET", "TURNSTILE_SITE_KEY"])
  migration_secret_names = toset(["DATABASE_URL_DIRECT"])
  runtime_secret_names   = setunion(local.backend_secret_names, local.frontend_secret_names, local.migration_secret_names)

  workload_secret_names = {
    api       = local.backend_secret_names
    worker    = local.backend_secret_names
    frontend  = local.frontend_secret_names
    migration = local.migration_secret_names
  }

  workload_log_group_arns = {
    api       = aws_cloudwatch_log_group.api.arn
    worker    = aws_cloudwatch_log_group.worker.arn
    frontend  = aws_cloudwatch_log_group.frontend.arn
    migration = aws_cloudwatch_log_group.migration.arn
  }

  workload_repository_arns = {
    api       = aws_ecr_repository.backend.arn
    worker    = aws_ecr_repository.backend.arn
    frontend  = aws_ecr_repository.frontend.arn
    migration = aws_ecr_repository.backend.arn
  }

  github_oidc_provider_arn = var.create_github_oidc_provider ? try(aws_iam_openid_connect_provider.github[0].arn, "") : var.github_oidc_provider_arn
  github_oidc_subject = (
    var.github_repository != "" && var.github_environment != "" ?
    "repo:${var.github_repository}:environment:${var.github_environment}" :
    ""
  )

  # Production and any stack explicitly claiming HA are treated as live edge
  # profiles. They cannot fall back to the staging-only CloudFront hostname or
  # plaintext VPC-origin transport.
  protected_edge_required = var.environment == "production" || var.availability_profile == "ha"

  plaintext_environment = {
    api      = var.api_environment
    worker   = var.worker_environment
    frontend = var.frontend_environment
  }

  reviewed_required_environment_names = {
    api      = toset(split(",", "ACCEPTING_NEW_ANALYSES,ANALYSIS_TIMEOUT_SEC,API_ORIGIN,ARQ_HEALTH_KEY,ASYNC_STRICT_HEALTH,AUTH_MODE,AWS_DEFAULT_REGION,AWS_REGION,AWS_S3_US_EAST_1_REGIONAL_ENDPOINT,BATCH_BLOB_DIR,BLOB_STORAGE_PATH,DASHBOARD_ORIGIN,DEPLOYMENT_ENVIRONMENT,DESIGN_GENERATION_CONCURRENCY,DESIGN_GENERATION_TIMEOUT_SECONDS,DIRECT_UPLOAD_PREP_CONCURRENCY,DIRECT_UPLOAD_S3_BUCKET,DIRECT_UPLOAD_S3_KMS_KEY_ID,DIRECT_UPLOAD_S3_PREFIX,DIRECT_UPLOAD_S3_REGION,HOME,LOG_LEVEL,MAGIC_LINK_ENABLED,MAX_UPLOAD_MB,MESH_BLOB_DIR,METRICS_ENABLED,OBJECT_STORE_BACKEND,OBJECT_STORE_S3_BUCKET,OBJECT_STORE_S3_KMS_KEY_ID,OBJECT_STORE_S3_PREFIX,OBJECT_STORE_S3_REGION,PASSWORD_LOGIN_ENABLED,PDF_CACHE_DIR,PORT,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED,PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED,PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED,PRODUCTION_OBSERVABILITY_REQUIRED,PRODUCTION_SECURITY_HEADERS_REQUIRED,PRODUCTION_SSRF_GUARD_REQUIRED,PRODUCTION_STORAGE_REQUIRED,PRODUCTION_TLS_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PROOFSHAPE_BUILD_ID,PUBLIC_PASSWORD_SIGNUP_ENABLED,RATE_LIBRARY_ENABLED,RECON_BLOB_DIR,RECONSTRUCTION_ALLOW_REMOTE_EGRESS,RECONSTRUCTION_BACKEND,RELEASE,SAM3D_CACHE_DIR,SAM3D_ENABLED,SECRET_ENFORCEMENT_ENABLED,SECURITY_HEADERS_ENABLED,SESSION_COOKIE_DOMAIN,TMPDIR,WEBHOOK_SSRF_GUARD_ENABLED,WORKER_STRICT_HEALTH,XDG_CACHE_HOME"))
    worker   = toset(split(",", "ACCEPTING_NEW_ANALYSES,ANALYSIS_TIMEOUT_SEC,API_ORIGIN,ARQ_HEALTH_KEY,ASYNC_STRICT_HEALTH,AUTH_MODE,AWS_DEFAULT_REGION,AWS_REGION,AWS_S3_US_EAST_1_REGIONAL_ENDPOINT,BATCH_BLOB_DIR,BLOB_STORAGE_PATH,DASHBOARD_ORIGIN,DEFAULT_BATCH_CONCURRENCY,DEPLOYMENT_ENVIRONMENT,DESIGN_GENERATION_CONCURRENCY,DESIGN_GENERATION_TIMEOUT_SECONDS,DIRECT_UPLOAD_PREP_CONCURRENCY,DIRECT_UPLOAD_S3_BUCKET,DIRECT_UPLOAD_S3_KMS_KEY_ID,DIRECT_UPLOAD_S3_PREFIX,DIRECT_UPLOAD_S3_REGION,HOME,LOG_LEVEL,MAGIC_LINK_ENABLED,MAX_UPLOAD_MB,MESH_BLOB_DIR,METRICS_ENABLED,OBJECT_STORE_BACKEND,OBJECT_STORE_S3_BUCKET,OBJECT_STORE_S3_KMS_KEY_ID,OBJECT_STORE_S3_PREFIX,OBJECT_STORE_S3_REGION,PASSWORD_LOGIN_ENABLED,PDF_CACHE_DIR,PORT,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED,PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED,PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED,PRODUCTION_OBSERVABILITY_REQUIRED,PRODUCTION_SECURITY_HEADERS_REQUIRED,PRODUCTION_SSRF_GUARD_REQUIRED,PRODUCTION_STORAGE_REQUIRED,PRODUCTION_TLS_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PROOFSHAPE_BUILD_ID,PUBLIC_PASSWORD_SIGNUP_ENABLED,RATE_LIBRARY_ENABLED,RECON_BLOB_DIR,RECONSTRUCTION_ALLOW_REMOTE_EGRESS,RECONSTRUCTION_BACKEND,RELEASE,SAM3D_CACHE_DIR,SAM3D_ENABLED,SECRET_ENFORCEMENT_ENABLED,SECURITY_HEADERS_ENABLED,SESSION_COOKIE_DOMAIN,TMPDIR,WEBHOOK_SSRF_GUARD_ENABLED,WORKER_STRICT_HEALTH,XDG_CACHE_HOME"))
    frontend = toset(split(",", "API_BASE,API_ORIGIN,AUTH_MODE,AUTH_PROXY_CLIENT_IP_SOURCE,DASHBOARD_ORIGIN,DEPLOYMENT_ENVIRONMENT,DIRECT_UPLOAD_ORIGIN,HOME,MAGIC_LINK_UI_ENABLED,NEXT_PUBLIC_SHOW_DEV_TOOLS,NEXT_PUBLIC_VERIFY_UI,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_DIRECT_UPLOAD_REQUIRED,PRODUCTION_PUBLIC_API_TLS_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PROOFSHAPE_BUILD_ID,PUBLIC_PASSWORD_SIGNUP_ENABLED,RELEASE,TMPDIR"))
  }
}

# Centralized fail-closed relationships that Terraform variable validation
# cannot express across multiple variables and resources.
resource "terraform_data" "contract" {
  input = local.name

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "The active AWS account does not match aws_account_id."
    }

    precondition {
      condition     = contains(local.cloudfront_vpc_origin_supported_regions, var.aws_region)
      error_message = "aws_region is not in CloudFront's current commercial VPC-origin region list."
    }

    precondition {
      condition = alltrue([
        for zone in data.aws_availability_zone.selected :
        !contains(local.cloudfront_vpc_origin_unsupported_zone_ids, zone.zone_id)
      ])
      error_message = "A selected availability zone is excluded from CloudFront VPC origins in this region."
    }

    precondition {
      condition = (
        (var.environment == "staging" && var.application_environment == "saas-staging") ||
        (var.environment == "production" && var.application_environment == "saas-production")
      )
      error_message = "environment and application_environment must identify the same isolated plane."
    }

    precondition {
      condition     = var.cloudfront_alias == "" || var.cloudfront_acm_certificate_arn != ""
      error_message = "cloudfront_alias requires a us-east-1 ACM certificate ARN."
    }

    precondition {
      condition = var.cloudfront_acm_certificate_arn == "" || can(regex(
        "^arn:${data.aws_partition.current.partition}:acm:us-east-1:${var.aws_account_id}:certificate/[0-9a-f-]+$",
        var.cloudfront_acm_certificate_arn,
      ))
      error_message = "cloudfront_acm_certificate_arn must be a certificate in us-east-1 and the configured account."
    }

    precondition {
      condition = var.alb_origin_acm_certificate_arn == "" || can(regex(
        "^arn:${data.aws_partition.current.partition}:acm:${var.aws_region}:${var.aws_account_id}:certificate/[0-9a-f-]+$",
        var.alb_origin_acm_certificate_arn,
      ))
      error_message = "alb_origin_acm_certificate_arn must be a regional ACM certificate in the configured account."
    }

    precondition {
      condition = var.cloudfront_origin_protocol_policy != "https-only" || (
        var.cloudfront_alias != "" &&
        var.cloudfront_acm_certificate_arn != "" &&
        var.alb_origin_acm_certificate_arn != ""
      )
      error_message = "https-only CloudFront-to-ALB transport requires a custom alias plus us-east-1 viewer and regional ALB ACM certificates."
    }

    precondition {
      condition = !local.protected_edge_required || (
        var.cloudfront_alias != "" &&
        var.cloudfront_origin_protocol_policy == "https-only" &&
        var.cloudfront_acm_certificate_arn != "" &&
        var.alb_origin_acm_certificate_arn != "" &&
        var.enable_waf &&
        var.enable_waf_logging &&
        var.cloudfront_access_log_bucket_domain != "" &&
        var.alb_access_log_bucket_name != "" &&
        var.alb_deletion_protection &&
        var.cloudfront_retain_on_delete
      )
      error_message = "Production/HA is blocked until custom-domain TLS 1.2, HTTPS VPC-origin transport, WAF+WAF logging, CloudFront+ALB access logging, ALB deletion protection, and CloudFront retain-on-delete are configured."
    }

    precondition {
      condition = var.environment != "production" || (
        var.rds_deletion_protection &&
        var.rds_backup_retention_days >= 7 &&
        !var.rds_skip_final_snapshot &&
        !var.rds_delete_automated_backups &&
        var.cache_snapshot_retention_days >= 1 &&
        var.cache_final_snapshot_identifier != "" &&
        var.api_capacity_provider == "FARGATE" &&
        var.worker_capacity_provider == "FARGATE" &&
        var.frontend_capacity_provider == "FARGATE" &&
        (var.s3_noncurrent_version_expiration_days == null || var.s3_noncurrent_version_expiration_days >= 365) &&
        !var.s3_force_destroy &&
        !var.ecr_force_delete
      )
      error_message = "Production requires on-demand Fargate, RDS/cache snapshot and PITR retention, durable evidence retention, and non-destructive RDS/S3/ECR deletion settings."
    }

    precondition {
      condition     = !var.enable_services || var.enable_workloads
      error_message = "enable_services requires enable_workloads."
    }

    precondition {
      condition     = !var.enable_services || var.cache_authentication_confirmed
      error_message = "API/worker services are blocked until ElastiCache AUTH is enabled out of band and cache_authentication_confirmed is set true."
    }

    precondition {
      condition     = !var.enable_services || var.transient_upload_contract_confirmed
      error_message = "Services are blocked until the release image's dedicated transient-upload bucket contract is reviewed, passes the exact-image workflow gate, and transient_upload_contract_confirmed is set true."
    }

    precondition {
      condition     = !var.enable_workloads || can(regex("^[0-9a-f]{40}$", var.initial_release_id))
      error_message = "Enabled workloads require initial_release_id to be the exact lowercase 40-character release SHA; 'bootstrap' is never a live release identity."
    }

    precondition {
      condition = alltrue([
        for workload, resources in {
          api       = [var.api_cpu, var.api_memory]
          worker    = [var.worker_cpu, var.worker_memory]
          frontend  = [var.frontend_cpu, var.frontend_memory]
          migration = [var.migration_cpu, var.migration_memory]
        } : contains(lookup(local.fargate_valid_memory, tostring(resources[0]), toset([])), resources[1])
      ])
      error_message = "API, worker, frontend, and migration CPU/memory values must be valid AWS Fargate combinations."
    }

    precondition {
      condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.fargate_platform_version))
      error_message = "fargate_platform_version must be an explicit numeric version, never LATEST."
    }

    precondition {
      condition = alltrue(flatten([
        for workload, environment in local.plaintext_environment : [
          length(setintersection(
            toset(keys(environment)),
            setunion(local.reviewed_required_environment_names[workload], local.workload_secret_names[workload]),
          )) == 0,
          alltrue([
            for name in keys(environment) :
            !contains(["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"], upper(name)) &&
            !can(regex("(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY|CREDENTIAL)", upper(name)))
          ]),
        ]
      ]))
      error_message = "Additional plaintext environment maps cannot override reviewed baseline/secret keys or contain credential-like names; put secrets in runtime_secret_arns."
    }

    precondition {
      condition = length(setsubtract(
        toset(keys(var.runtime_secret_arns)),
        local.runtime_secret_names,
      )) == 0
      error_message = "runtime_secret_arns contains an environment variable that is not part of the reviewed runtime contract."
    }

    precondition {
      condition = alltrue([
        for arn in values(var.runtime_secret_arns) : can(regex(
          "^arn:${data.aws_partition.current.partition}:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:.+$",
          arn,
        ))
      ])
      error_message = "Every externally managed runtime secret must be in the configured partition, region, and account."
    }

    precondition {
      condition = var.cache_auth_token_secret_arn == "" || can(regex(
        "^arn:${data.aws_partition.current.partition}:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:.+$",
        var.cache_auth_token_secret_arn,
      ))
      error_message = "cache_auth_token_secret_arn must be in the configured partition, region, and account."
    }

    precondition {
      condition = alltrue([
        for arn in var.external_secret_kms_key_arns : can(regex(
          "^arn:${data.aws_partition.current.partition}:kms:${var.aws_region}:${var.aws_account_id}:key/[0-9a-f-]+$",
          arn,
        ))
      ])
      error_message = "External secret KMS keys must be customer-managed keys in the configured partition, region, and account."
    }

    precondition {
      condition = !var.enable_services || (
        var.api_desired_count >= 1 &&
        var.worker_desired_count >= 1 &&
        var.frontend_desired_count >= 1
      )
      error_message = "Enabled services require at least one task for API, worker, and frontend."
    }

    precondition {
      condition = !var.enable_autoscaling || (
        var.api_autoscaling_min >= 1 && var.api_autoscaling_max >= var.api_autoscaling_min &&
        var.worker_autoscaling_min >= 1 && var.worker_autoscaling_max >= var.worker_autoscaling_min &&
        var.frontend_autoscaling_min >= 1 && var.frontend_autoscaling_max >= var.frontend_autoscaling_min
      )
      error_message = "Each autoscaling maximum must be greater than or equal to a positive minimum."
    }

    precondition {
      condition = !var.enable_workloads || (
        startswith(var.backend_image, "${aws_ecr_repository.backend.repository_url}@sha256:") &&
        startswith(var.frontend_image, "${aws_ecr_repository.frontend.repository_url}@sha256:")
      )
      error_message = "Enabled workloads require digest-qualified images from this stack's backend and frontend ECR repositories."
    }

    precondition {
      condition = var.availability_profile != "ha" || (
        var.rds_multi_az &&
        var.cache_node_count >= 2 &&
        var.api_capacity_provider == "FARGATE" &&
        var.worker_capacity_provider == "FARGATE" &&
        var.frontend_capacity_provider == "FARGATE" &&
        (!var.enable_services || (
          var.api_desired_count >= 2 &&
          var.worker_desired_count >= 2 &&
          var.frontend_desired_count >= 2
        ))
      )
      error_message = "The ha availability profile requires on-demand Fargate, Multi-AZ RDS, at least two cache nodes, and at least two tasks per enabled service."
    }

    precondition {
      condition     = !var.enable_waf_logging || var.enable_waf
      error_message = "enable_waf_logging requires enable_waf."
    }

    precondition {
      condition     = !var.enable_budget || length(var.budget_alert_emails) > 0
      error_message = "enable_budget requires at least one budget_alert_emails recipient."
    }

    precondition {
      condition = !var.enable_github_oidc || (
        var.github_repository != "" &&
        var.github_environment == "aws-commercial-${var.environment}" &&
        local.github_oidc_provider_arn != "" &&
        local.github_oidc_subject == "repo:${var.github_repository}:environment:${var.github_environment}"
      )
      error_message = "GitHub OIDC requires an exact repository, aws-commercial-<environment>, provider ARN/create flag, and exact subject."
    }

    precondition {
      condition = !var.enable_github_oidc || var.create_github_oidc_provider || can(regex(
        "^arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com$",
        var.github_oidc_provider_arn,
      ))
      error_message = "github_oidc_provider_arn must be the GitHub Actions OIDC provider in the configured account."
    }
  }
}
