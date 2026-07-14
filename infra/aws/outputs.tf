output "canonical_public_origin" {
  description = "Only supported HTTPS release origin. Uses the CloudFront hostname until an optional custom alias is configured."
  value       = local.canonical_public_origin
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID."
  value       = aws_cloudfront_distribution.app.id
}

output "cloudfront_domain_name" {
  description = "AWS-provided CloudFront hostname that works without a purchased domain."
  value       = aws_cloudfront_distribution.app.domain_name
}

output "alb_origin_dns_name" {
  description = "Private CloudFront VPC origin only. This ALB hostname is unreachable from the internet and is never a ProofShape release URL."
  value       = aws_lb.origin.dns_name
}

output "cloudfront_vpc_origin_id" {
  description = "CloudFront VPC-origin ID protecting the private ALB."
  value       = aws_cloudfront_vpc_origin.alb.id
}

output "vpc_id" {
  description = "Environment VPC ID."
  value       = aws_vpc.main.id
}

output "availability_zones" {
  description = "The two AZs used by this stack."
  value       = local.selected_availability_zones
}

output "public_subnet_ids" {
  description = "Public Fargate subnet IDs. Fargate service definitions assign public IPs explicitly; the ALB is private."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "No-default-route RDS/ElastiCache subnet IDs."
  value       = aws_subnet.private[*].id
}

output "artifact_bucket_name" {
  description = "Encrypted, versioned durable customer-evidence bucket."
  value       = aws_s3_bucket.artifacts.id
}

output "transient_upload_bucket" {
  description = "Encrypted, deliberately unversioned incoming-upload bucket with short lifecycle cleanup."
  value = {
    contract_confirmed = var.transient_upload_contract_confirmed
    expiration_days    = var.transient_upload_expiration_days
    name               = aws_s3_bucket.transient_uploads.id
    public_origin      = local.direct_upload_public_origin
    versioning         = "policy-denied"
  }
}

output "artifact_kms_key_arn" {
  description = "Customer-managed KMS key used by the commercial environment."
  value       = aws_kms_key.main.arn
}

output "backend_ecr_repository" {
  description = "Immutable/scanned backend ECR repository."
  value = {
    name = aws_ecr_repository.backend.name
    uri  = aws_ecr_repository.backend.repository_url
  }
}

output "frontend_ecr_repository" {
  description = "Immutable/scanned frontend ECR repository."
  value = {
    name = aws_ecr_repository.frontend.name
    uri  = aws_ecr_repository.frontend.repository_url
  }
}

output "rds" {
  description = "Private RDS connection metadata. The generated administrator secret value is not exposed."
  value = {
    address           = aws_db_instance.postgres.address
    database          = aws_db_instance.postgres.db_name
    master_secret_arn = try(aws_db_instance.postgres.master_user_secret[0].secret_arn, null)
    multi_az          = aws_db_instance.postgres.multi_az
    port              = aws_db_instance.postgres.port
  }
}

output "elasticache" {
  description = "Private TLS Redis connection metadata and the explicit out-of-band AUTH gate."
  value = {
    automatic_failover = aws_elasticache_replication_group.redis.automatic_failover_enabled
    auth_confirmed     = var.cache_authentication_confirmed
    auth_secret_arn    = local.cache_auth_token_secret_arn
    endpoint           = aws_elasticache_replication_group.redis.primary_endpoint_address
    port               = aws_elasticache_replication_group.redis.port
    replicas           = var.cache_node_count
  }
}

output "runtime_secret_arns" {
  description = "Secret metadata references required by ECS. Terraform creates no SecretString versions."
  value       = local.runtime_secret_arns
}

output "ecs_cluster_arn" {
  description = "Commercial ECS cluster ARN."
  value       = aws_ecs_cluster.main.arn
}

output "ecs_services" {
  description = "Long-running service names. Empty ARNs mean services remain intentionally disabled."
  value = {
    api = {
      name = "${local.name}-api"
      arn  = try(aws_ecs_service.api[0].id, null)
    }
    frontend = {
      name = "${local.name}-frontend"
      arn  = try(aws_ecs_service.frontend[0].id, null)
    }
    worker = {
      name = "${local.name}-worker"
      arn  = try(aws_ecs_service.worker[0].id, null)
    }
  }
}

output "ecs_task_definitions" {
  description = "Initial digest-pinned task definitions, including the one-shot Alembic migration family."
  value = {
    api       = try(aws_ecs_task_definition.api[0].arn, null)
    frontend  = try(aws_ecs_task_definition.frontend[0].arn, null)
    migration = try(aws_ecs_task_definition.migration[0].arn, null)
    worker    = try(aws_ecs_task_definition.worker[0].arn, null)
  }
}

output "cloud_map_api" {
  description = "Private API discovery endpoint for in-VPC clients. The released frontend still uses canonical HTTPS API_BASE."
  value       = "http://api.${aws_service_discovery_private_dns_namespace.main.name}:8000"
}

output "github_deploy_role_arn" {
  description = "Environment/repository-scoped GitHub OIDC deployment role."
  value       = try(aws_iam_role.github_deploy[0].arn, null)
}

output "alarm_topic_arns" {
  description = "Regional alarm topics. Subscribe operators outside this stack."
  value = compact([
    try(aws_sns_topic.alarms[0].arn, ""),
    try(aws_sns_topic.edge_alarms[0].arn, ""),
  ])
}

output "availability_posture" {
  description = "Machine-readable, honest availability posture for operator review."
  value = {
    declared_profile                    = var.availability_profile
    availability_zones                  = local.selected_availability_zones
    api_task_count                      = var.enable_services ? var.api_desired_count : 0
    api_capacity_provider               = var.api_capacity_provider
    cache_automatic_failover            = var.cache_node_count > 1
    cache_auth_confirmed                = var.cache_authentication_confirmed
    cache_node_count                    = var.cache_node_count
    frontend_task_count                 = var.enable_services ? var.frontend_desired_count : 0
    frontend_capacity_provider          = var.frontend_capacity_provider
    fargate_platform_version            = var.fargate_platform_version
    rds_multi_az                        = var.rds_multi_az
    services_enabled                    = var.enable_services
    transient_upload_contract_confirmed = var.transient_upload_contract_confirmed
    worker_task_count                   = var.enable_services ? var.worker_desired_count : 0
    worker_capacity_provider            = var.worker_capacity_provider
  }
}

output "promotion_environment_variables" {
  description = "Non-secret values to copy into the matching protected GitHub environment."
  value = {
    AWS_ACCOUNT_ID                         = var.aws_account_id
    AWS_COMMERCIAL_BOUNDARY                = "proofshape-commercial"
    AWS_DASHBOARD_ORIGIN                   = local.canonical_public_origin
    AWS_DEPLOY_ROLE_ARN                    = try(aws_iam_role.github_deploy[0].arn, "")
    AWS_DIRECT_UPLOAD_ORIGIN               = local.direct_upload_public_origin
    AWS_ECR_BACKEND_REPOSITORY             = aws_ecr_repository.backend.name
    AWS_ECR_FRONTEND_REPOSITORY            = aws_ecr_repository.frontend.name
    AWS_ECS_API_BASE_TASK_DEFINITION       = try(aws_ecs_task_definition.api[0].arn, "")
    AWS_ECS_API_SERVICE                    = "${local.name}-api"
    AWS_ECS_CLUSTER                        = aws_ecs_cluster.main.name
    AWS_ECS_FRONTEND_BASE_TASK_DEFINITION  = try(aws_ecs_task_definition.frontend[0].arn, "")
    AWS_ECS_FRONTEND_SERVICE               = "${local.name}-frontend"
    AWS_ECS_MIGRATION_BASE_TASK_DEFINITION = try(aws_ecs_task_definition.migration[0].arn, "")
    AWS_ECS_MIGRATION_SECURITY_GROUP       = aws_security_group.migration.id
    AWS_ECS_PLATFORM_VERSION               = var.fargate_platform_version
    AWS_ECS_PUBLIC_SUBNET_IDS              = join(",", aws_subnet.public[*].id)
    AWS_ECS_WORKER_BASE_TASK_DEFINITION    = try(aws_ecs_task_definition.worker[0].arn, "")
    AWS_ECS_WORKER_SERVICE                 = "${local.name}-worker"
    AWS_PUBLIC_API_ORIGIN                  = local.canonical_public_origin
    AWS_REGION                             = var.aws_region
    AWS_RUNTIME_SECRET_ARNS                = join(",", sort(values(local.runtime_secret_arns)))
  }
}
