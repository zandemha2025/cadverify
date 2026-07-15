data "aws_iam_policy_document" "kms" {
  statement {
    sid    = "AccountAdministration"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "CloudWatchLogsEncryption"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.${data.aws_partition.current.dns_suffix}"]
    }

    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey*",
      "kms:ReEncrypt*",
    ]
    resources = ["*"]

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:*"]
    }
  }

  statement {
    sid    = "SnsEncryption"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["sns.${data.aws_partition.current.dns_suffix}"]
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }

  statement {
    sid    = "CloudWatchAlarmToSnsEncryption"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.${data.aws_partition.current.dns_suffix}"]
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_kms_key" "main" {
  description             = "${local.name} application, data, logs, secrets, and registry encryption"
  deletion_window_in_days = var.kms_deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms.json

  tags = {
    Name = "${local.name}-main"
  }
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}-main"
  target_key_id = aws_kms_key.main.key_id
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/proofshape/${var.environment}/ecs/api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/proofshape/${var.environment}/ecs/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/proofshape/${var.environment}/ecs/frontend"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/proofshape/${var.environment}/ecs/migration"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "rds_postgresql" {
  name              = "/aws/rds/instance/${local.name}/postgresql"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "rds_upgrade" {
  name              = "/aws/rds/instance/${local.name}/upgrade"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "cache_engine" {
  name              = "/proofshape/${var.environment}/elasticache/engine"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "cache_slow" {
  name              = "/proofshape/${var.environment}/elasticache/slow"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_cloudwatch_log_group" "vpc_flow" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  name              = "/proofshape/${var.environment}/vpc/flow"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}
