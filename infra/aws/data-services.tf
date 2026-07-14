resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name}-database"
  }
}

resource "aws_db_parameter_group" "postgres" {
  name        = local.name
  family      = var.rds_parameter_group_family
  description = "ProofShape PostgreSQL TLS baseline"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "postgres" {
  identifier = local.name

  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  db_name  = var.rds_database_name
  username = var.rds_master_username
  port     = var.rds_port

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.main.arn

  allocated_storage     = var.rds_allocated_storage_gib
  max_allocated_storage = var.rds_max_allocated_storage_gib
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.main.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.postgres.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = var.rds_multi_az

  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:05:00-sun:06:00"
  copy_tags_to_snapshot   = true

  deletion_protection       = var.rds_deletion_protection
  skip_final_snapshot       = var.rds_skip_final_snapshot
  final_snapshot_identifier = var.rds_skip_final_snapshot ? null : "${local.name}-final"
  delete_automated_backups  = var.rds_delete_automated_backups

  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false
  apply_immediately           = var.rds_apply_immediately

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  performance_insights_enabled          = var.rds_performance_insights_enabled
  performance_insights_kms_key_id       = var.rds_performance_insights_enabled ? aws_kms_key.main.arn : null
  performance_insights_retention_period = var.rds_performance_insights_enabled ? var.rds_performance_insights_retention_days : null

  iam_database_authentication_enabled = true

  depends_on = [
    aws_cloudwatch_log_group.rds_postgresql,
    aws_cloudwatch_log_group.rds_upgrade,
  ]
}

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = local.name
  description          = "ProofShape ${var.environment} private async tier"

  engine         = "redis"
  engine_version = var.cache_engine_version
  node_type      = var.cache_node_type
  port           = 6379

  num_cache_clusters         = var.cache_node_count
  automatic_failover_enabled = var.cache_node_count > 1
  multi_az_enabled           = var.cache_node_count > 1

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.cache.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.main.arn
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"

  snapshot_retention_limit = var.cache_snapshot_retention_days
  snapshot_window          = "01:00-02:00"
  maintenance_window       = "sun:06:00-sun:07:00"
  final_snapshot_identifier = (
    var.cache_final_snapshot_identifier != "" ? var.cache_final_snapshot_identifier : null
  )

  auto_minor_version_upgrade = true
  apply_immediately          = var.cache_apply_immediately

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.cache_engine.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "engine-log"
  }

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.cache_slow.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  depends_on = [
    aws_cloudwatch_log_group.cache_engine,
    aws_cloudwatch_log_group.cache_slow,
  ]

  # AUTH is applied by scripts/ops/aws-enable-cache-auth.sh from a Secrets
  # Manager value. Ignoring these provider fields preserves that out-of-band
  # control and prevents Terraform from attempting to remove or rotate it.
  lifecycle {
    ignore_changes = [auth_token, auth_token_update_strategy]
  }
}
