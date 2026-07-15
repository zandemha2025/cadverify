resource "aws_sns_topic" "alarms" {
  count = var.enable_alarms && var.create_alarm_topic ? 1 : 0

  name              = "${local.name}-alarms"
  kms_master_key_id = aws_kms_key.main.arn
}

resource "aws_sns_topic" "edge_alarms" {
  count    = var.enable_alarms && var.create_alarm_topic && var.aws_region != "us-east-1" ? 1 : 0
  provider = aws.us_east_1

  name              = "${local.name}-edge-alarms"
  kms_master_key_id = "alias/aws/sns"
}

locals {
  alarm_actions = distinct(concat(
    var.alarm_action_arns,
    var.enable_alarms && var.create_alarm_topic ? [aws_sns_topic.alarms[0].arn] : [],
  ))

  cloudfront_alarm_actions = (
    var.enable_alarms && var.create_alarm_topic ? (
      var.aws_region == "us-east-1" ? [aws_sns_topic.alarms[0].arn] : [aws_sns_topic.edge_alarms[0].arn]
      ) : (
      var.enable_alarms ? [
        for arn in var.alarm_action_arns : arn if can(regex(":sns:us-east-1:", arn))
      ] : []
    )
  )

  alarm_services = var.enable_alarms && var.enable_services ? {
    api      = aws_ecs_service.api[0].name
    frontend = aws_ecs_service.frontend[0].name
    worker   = aws_ecs_service.worker[0].name
  } : {}
}

resource "aws_cloudwatch_metric_alarm" "cloudfront_5xx" {
  count    = var.enable_alarms ? 1 : 0
  provider = aws.us_east_1

  alarm_name          = "${local.name}-cloudfront-5xx-rate"
  alarm_description   = "CloudFront viewer 5xx error rate exceeded 5 percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "5xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = 60
  statistic           = "Average"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cloudfront_alarm_actions
  ok_actions          = local.cloudfront_alarm_actions

  dimensions = {
    DistributionId = aws_cloudfront_distribution.app.id
    Region         = "Global"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-alb-5xx"
  alarm_description   = "Origin ALB produced elevated 5xx responses"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.origin.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_unhealthy" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-api-unhealthy-targets"
  alarm_description   = "One or more API targets are unhealthy"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.origin.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "frontend_unhealthy" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-frontend-unhealthy-targets"
  alarm_description   = "One or more frontend targets are unhealthy"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.origin.arn_suffix
    TargetGroup  = aws_lb_target_group.frontend.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  for_each = local.alarm_services

  alarm_name          = "${local.name}-${each.key}-cpu-high"
  alarm_description   = "${each.key} ECS CPU remained above 85 percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = each.value
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory" {
  for_each = local.alarm_services

  alarm_name          = "${local.name}-${each.key}-memory-high"
  alarm_description   = "${each.key} ECS memory remained above 90 percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 90
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = each.value
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-rds-cpu-high"
  alarm_description   = "RDS CPU remained above 80 percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-rds-free-storage-low"
  alarm_description   = "RDS free storage fell below 5 GiB"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120
  treat_missing_data  = "missing"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "cache_cpu" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${local.name}-cache-engine-cpu-high"
  alarm_description   = "ElastiCache engine CPU remained above 80 percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  metric_name         = "EngineCPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.redis.id
  }
}

resource "aws_budgets_budget" "monthly" {
  count = var.enable_budget ? 1 : 0

  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_emails
  }
}
