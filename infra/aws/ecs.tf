resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = {
    Name = local.name
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 1
    weight            = 1
  }
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.environment}.proofshape.internal"
  description = "ProofShape commercial ${var.environment} service discovery"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }

  health_check_custom_config {}
}

locals {
  backend_required_environment = {
    ACCEPTING_NEW_ANALYSES = "true"
    # Return the application's structured timeout before CloudFront's default
    # 60-second origin-response quota can turn it into a generic viewer 504.
    ANALYSIS_TIMEOUT_SEC                         = "50"
    API_ORIGIN                                   = local.canonical_public_origin
    ARQ_HEALTH_KEY                               = "arq:queue:health-check"
    ASYNC_STRICT_HEALTH                          = "1"
    AUTH_MODE                                    = "password"
    AWS_DEFAULT_REGION                           = var.aws_region
    AWS_REGION                                   = var.aws_region
    AWS_S3_US_EAST_1_REGIONAL_ENDPOINT           = "regional"
    BATCH_BLOB_DIR                               = "/tmp/proofshape/batch"
    BLOB_STORAGE_PATH                            = "/tmp/proofshape/blobs"
    DASHBOARD_ORIGIN                             = local.canonical_public_origin
    DEPLOYMENT_ENVIRONMENT                       = var.application_environment
    DESIGN_GENERATION_CONCURRENCY                = "2"
    DESIGN_GENERATION_TIMEOUT_SECONDS            = "45"
    DIRECT_UPLOAD_S3_BUCKET                      = aws_s3_bucket.transient_uploads.id
    DIRECT_UPLOAD_S3_KMS_KEY_ID                  = aws_kms_key.main.arn
    DIRECT_UPLOAD_S3_PREFIX                      = var.environment
    DIRECT_UPLOAD_S3_REGION                      = var.aws_region
    DIRECT_UPLOAD_PREP_CONCURRENCY               = "1"
    HOME                                         = "/tmp/proofshape/home"
    LOG_LEVEL                                    = "INFO"
    MAGIC_LINK_ENABLED                           = "true"
    MAX_UPLOAD_MB                                = "100"
    MESH_BLOB_DIR                                = "/tmp/proofshape/meshes"
    METRICS_ENABLED                              = "0"
    OBJECT_STORE_BACKEND                         = "s3"
    OBJECT_STORE_S3_BUCKET                       = aws_s3_bucket.artifacts.id
    OBJECT_STORE_S3_KMS_KEY_ID                   = aws_kms_key.main.arn
    OBJECT_STORE_S3_PREFIX                       = var.environment
    OBJECT_STORE_S3_REGION                       = var.aws_region
    PASSWORD_LOGIN_ENABLED                       = "true"
    PDF_CACHE_DIR                                = "/tmp/proofshape/pdf-cache"
    PORT                                         = "8000"
    PRODUCTION_AUTH_PROXY_REQUIRED               = "1"
    PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED    = "1"
    PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED         = "1"
    PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED = "1"
    PRODUCTION_OBSERVABILITY_REQUIRED            = "1"
    PRODUCTION_SECURITY_HEADERS_REQUIRED         = "1"
    PRODUCTION_SSRF_GUARD_REQUIRED               = "1"
    PRODUCTION_STORAGE_REQUIRED                  = "1"
    PRODUCTION_TLS_REQUIRED                      = "1"
    PRODUCTION_VERIFIED_SIGNUP_REQUIRED          = "1"
    PROOFSHAPE_BUILD_ID                          = var.initial_release_id
    PUBLIC_PASSWORD_SIGNUP_ENABLED               = "false"
    RATE_LIBRARY_ENABLED                         = "1"
    RECON_BLOB_DIR                               = "/tmp/proofshape/reconstruct"
    RECONSTRUCTION_ALLOW_REMOTE_EGRESS           = "0"
    RECONSTRUCTION_BACKEND                       = "local"
    RELEASE                                      = var.initial_release_id
    SAM3D_CACHE_DIR                              = "/tmp/proofshape/sam3d-cache"
    SAM3D_ENABLED                                = "false"
    SECRET_ENFORCEMENT_ENABLED                   = "1"
    SECURITY_HEADERS_ENABLED                     = "1"
    SESSION_COOKIE_DOMAIN                        = ""
    TMPDIR                                       = "/tmp"
    WEBHOOK_SSRF_GUARD_ENABLED                   = "1"
    WORKER_STRICT_HEALTH                         = "1"
    XDG_CACHE_HOME                               = "/tmp/proofshape/cache"
  }

  api_environment = merge(var.api_environment, local.backend_required_environment)
  worker_environment = merge(var.worker_environment, local.backend_required_environment, {
    DEFAULT_BATCH_CONCURRENCY = tostring(var.batch_default_concurrency)
  })

  frontend_required_environment = {
    API_BASE                            = local.canonical_public_origin
    API_ORIGIN                          = local.canonical_public_origin
    AUTH_MODE                           = "password"
    AUTH_PROXY_CLIENT_IP_SOURCE         = "cloudfront"
    DASHBOARD_ORIGIN                    = local.canonical_public_origin
    DEPLOYMENT_ENVIRONMENT              = var.application_environment
    DIRECT_UPLOAD_ORIGIN                = local.direct_upload_public_origin
    HOME                                = "/tmp"
    MAGIC_LINK_UI_ENABLED               = "1"
    NEXT_PUBLIC_SHOW_DEV_TOOLS          = "0"
    NEXT_PUBLIC_VERIFY_UI               = "1"
    PRODUCTION_AUTH_PROXY_REQUIRED      = "1"
    PRODUCTION_DIRECT_UPLOAD_REQUIRED   = "1"
    PRODUCTION_PUBLIC_API_TLS_REQUIRED  = "1"
    PRODUCTION_VERIFIED_SIGNUP_REQUIRED = "1"
    PROOFSHAPE_BUILD_ID                 = var.initial_release_id
    PUBLIC_PASSWORD_SIGNUP_ENABLED      = "0"
    RELEASE                             = var.initial_release_id
    TMPDIR                              = "/tmp"
  }

  frontend_environment = merge(var.frontend_environment, local.frontend_required_environment)

  awslogs_options = {
    api = {
      "awslogs-group"         = aws_cloudwatch_log_group.api.name
      "awslogs-region"        = var.aws_region
      "awslogs-stream-prefix" = "api"
      "max-buffer-size"       = "25m"
      "mode"                  = "non-blocking"
    }
    worker = {
      "awslogs-group"         = aws_cloudwatch_log_group.worker.name
      "awslogs-region"        = var.aws_region
      "awslogs-stream-prefix" = "worker"
      "max-buffer-size"       = "25m"
      "mode"                  = "non-blocking"
    }
    frontend = {
      "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
      "awslogs-region"        = var.aws_region
      "awslogs-stream-prefix" = "frontend"
      "max-buffer-size"       = "25m"
      "mode"                  = "non-blocking"
    }
    migration = {
      "awslogs-group"         = aws_cloudwatch_log_group.migration.name
      "awslogs-region"        = var.aws_region
      "awslogs-stream-prefix" = "migration"
      "max-buffer-size"       = "25m"
      "mode"                  = "non-blocking"
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  count = var.enable_workloads ? 1 : 0

  family                   = "${local.name}-api"
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.task["api"].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  ephemeral_storage {
    size_in_gib = var.backend_ephemeral_storage_gib
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.backend_image
      essential = true
      cpu       = var.api_cpu
      memory    = var.api_memory
      portMappings = [
        {
          name          = "api-http"
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
          appProtocol   = "http"
        },
      ]
      environment = [
        for name in sort(keys(local.api_environment)) : {
          name  = name
          value = local.api_environment[name]
        }
      ]
      secrets = [
        for name in sort(tolist(local.backend_secret_names)) : {
          name      = name
          valueFrom = local.runtime_secret_arns[name]
        }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()\"",
        ]
        interval    = 30
        retries     = 5
        startPeriod = 120
        timeout     = 10
      }
      linuxParameters = {
        initProcessEnabled = true
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = local.awslogs_options.api
      }
      mountPoints = [
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
      ]
      readonlyRootFilesystem = true
      stopTimeout            = 120
    },
  ])

  tags = {
    Component = "api"
  }

  depends_on = [aws_iam_role_policy.execution]
}

resource "aws_ecs_task_definition" "worker" {
  count = var.enable_workloads ? 1 : 0

  family                   = "${local.name}-worker"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.execution["worker"].arn
  task_role_arn            = aws_iam_role.task["worker"].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  ephemeral_storage {
    size_in_gib = var.backend_ephemeral_storage_gib
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.backend_image
      essential = true
      cpu       = var.worker_cpu
      memory    = var.worker_memory
      command   = ["arq", "src.jobs.worker.WorkerSettings"]
      environment = [
        for name in sort(keys(local.worker_environment)) : {
          name  = name
          value = local.worker_environment[name]
        }
      ]
      secrets = [
        for name in sort(tolist(local.backend_secret_names)) : {
          name      = name
          valueFrom = local.runtime_secret_arns[name]
        }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "arq src.jobs.worker.WorkerSettings --check",
        ]
        interval    = 30
        retries     = 5
        startPeriod = 120
        timeout     = 10
      }
      linuxParameters = {
        initProcessEnabled = true
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = local.awslogs_options.worker
      }
      mountPoints = [
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
      ]
      readonlyRootFilesystem = true
      stopTimeout            = 120
    },
  ])

  tags = {
    Component = "worker"
  }

  depends_on = [aws_iam_role_policy.execution]
}

resource "aws_ecs_task_definition" "frontend" {
  count = var.enable_workloads ? 1 : 0

  family                   = "${local.name}-frontend"
  cpu                      = tostring(var.frontend_cpu)
  memory                   = tostring(var.frontend_memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.execution["frontend"].arn
  task_role_arn            = aws_iam_role.task["frontend"].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "scratch"
  }

  volume {
    name = "next-cache"
  }

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = var.frontend_image
      essential = true
      cpu       = var.frontend_cpu
      memory    = var.frontend_memory
      portMappings = [
        {
          name          = "frontend-http"
          containerPort = 3000
          hostPort      = 3000
          protocol      = "tcp"
          appProtocol   = "http"
        },
      ]
      environment = [
        for name in sort(keys(local.frontend_environment)) : {
          name  = name
          value = local.frontend_environment[name]
        }
      ]
      secrets = [
        for name in sort(tolist(local.frontend_secret_names)) : {
          name      = name
          valueFrom = local.runtime_secret_arns[name]
        }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "node -e \"require('http').get('http://127.0.0.1:3000', r => process.exit(r.statusCode >= 200 && r.statusCode < 400 ? 0 : 1)).on('error', () => process.exit(1))\"",
        ]
        interval    = 30
        retries     = 5
        startPeriod = 60
        timeout     = 10
      }
      linuxParameters = {
        initProcessEnabled = true
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = local.awslogs_options.frontend
      }
      mountPoints = [
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
        {
          sourceVolume  = "next-cache"
          containerPath = "/app/.next/cache"
          readOnly      = false
        },
      ]
      readonlyRootFilesystem = true
      stopTimeout            = 60
    },
  ])

  tags = {
    Component = "frontend"
  }

  depends_on = [aws_iam_role_policy.execution]
}

resource "aws_ecs_task_definition" "migration" {
  count = var.enable_workloads ? 1 : 0

  family                   = "${local.name}-migration"
  cpu                      = tostring(var.migration_cpu)
  memory                   = tostring(var.migration_memory)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.execution["migration"].arn
  task_role_arn            = aws_iam_role.task["migration"].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    {
      name      = "migration"
      image     = var.backend_image
      essential = true
      cpu       = var.migration_cpu
      memory    = var.migration_memory
      command   = ["alembic", "upgrade", "head"]
      environment = [
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "HOME", value = "/tmp" },
        { name = "PROOFSHAPE_BUILD_ID", value = var.initial_release_id },
        { name = "RELEASE", value = var.initial_release_id },
        { name = "TMPDIR", value = "/tmp" },
        { name = "XDG_CACHE_HOME", value = "/tmp/cache" },
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = local.runtime_secret_arns["DATABASE_URL_DIRECT"]
        },
      ]
      linuxParameters = {
        initProcessEnabled = true
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = local.awslogs_options.migration
      }
      mountPoints = [
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
      ]
      readonlyRootFilesystem = true
      stopTimeout            = 120
    },
  ])

  tags = {
    Component = "migration"
  }

  depends_on = [aws_iam_role_policy.execution]
}

resource "aws_ecs_service" "api" {
  count = var.enable_services ? 1 : 0

  name             = "${local.name}-api"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.api[0].arn
  desired_count    = var.api_desired_count
  platform_version = var.fargate_platform_version

  capacity_provider_strategy {
    capacity_provider = var.api_capacity_provider
    weight            = 1
  }

  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent
  health_check_grace_period_seconds  = 180
  enable_ecs_managed_tags            = true
  propagate_tags                     = "TASK_DEFINITION"
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.api.id]
    subnets          = aws_subnet.public[*].id
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.api.arn
    container_name = "api"
    container_port = 8000
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_iam_role_policy.execution,
    aws_lb_listener_rule.api_primary_paths,
    aws_lb_listener_rule.api_secondary_paths,
  ]
}

resource "aws_ecs_service" "worker" {
  count = var.enable_services ? 1 : 0

  name             = "${local.name}-worker"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.worker[0].arn
  desired_count    = var.worker_desired_count
  platform_version = var.fargate_platform_version

  capacity_provider_strategy {
    capacity_provider = var.worker_capacity_provider
    weight            = 1
  }

  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent
  enable_ecs_managed_tags            = true
  propagate_tags                     = "TASK_DEFINITION"
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.worker.id]
    subnets          = aws_subnet.public[*].id
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_iam_role_policy.execution,
  ]
}

resource "aws_ecs_service" "frontend" {
  count = var.enable_services ? 1 : 0

  name             = "${local.name}-frontend"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.frontend[0].arn
  desired_count    = var.frontend_desired_count
  platform_version = var.fargate_platform_version

  capacity_provider_strategy {
    capacity_provider = var.frontend_capacity_provider
    weight            = 1
  }

  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent
  health_check_grace_period_seconds  = 120
  enable_ecs_managed_tags            = true
  propagate_tags                     = "TASK_DEFINITION"
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.frontend.id]
    subnets          = aws_subnet.public[*].id
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_iam_role_policy.execution,
    aws_lb_listener_rule.frontend_all_paths,
  ]
}

locals {
  autoscaling_services = var.enable_services && var.enable_autoscaling ? {
    api = {
      name = aws_ecs_service.api[0].name
      min  = var.api_autoscaling_min
      max  = var.api_autoscaling_max
    }
    frontend = {
      name = aws_ecs_service.frontend[0].name
      min  = var.frontend_autoscaling_min
      max  = var.frontend_autoscaling_max
    }
    worker = {
      name = aws_ecs_service.worker[0].name
      min  = var.worker_autoscaling_min
      max  = var.worker_autoscaling_max
    }
  } : {}
}

resource "aws_appautoscaling_target" "ecs" {
  for_each = local.autoscaling_services

  max_capacity       = each.value.max
  min_capacity       = each.value.min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${each.value.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ecs_cpu" {
  for_each = local.autoscaling_services

  name               = "${local.name}-${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = var.autoscaling_cpu_target

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "ecs_memory" {
  for_each = local.autoscaling_services

  name               = "${local.name}-${each.key}-memory"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = var.autoscaling_memory_target

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
  }
}
