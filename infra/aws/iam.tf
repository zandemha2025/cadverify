data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.${data.aws_partition.current.dns_suffix}"]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each = local.workload_secret_names

  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.workload_secret_names

  statement {
    sid       = "EcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullExactRepository"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.workload_repository_arns[each.key]]
  }

  statement {
    sid    = "WriteExactLogGroup"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${local.workload_log_group_arns[each.key]}:*"]
  }

  statement {
    sid       = "ReadExactRuntimeSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for name in each.value : local.runtime_secret_arns[name]]
  }

  statement {
    sid       = "DecryptRuntimeSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = distinct(concat([aws_kms_key.main.arn], var.external_secret_kms_key_arns))

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.${data.aws_partition.current.dns_suffix}"]
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.workload_secret_names

  name   = "least-privilege-execution"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution[each.key].json
}

resource "aws_iam_role" "task" {
  for_each = local.workload_secret_names

  name               = "${local.name}-${each.key}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "object_store_task" {
  statement {
    sid       = "ListEnvironmentPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        var.environment,
        "${var.environment}/*",
      ]
    }
  }

  statement {
    sid    = "ManageCurrentDurableObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/${var.environment}/*"]
  }

  # The durable bucket is versioned. DeleteObject may hide a current object,
  # but the role intentionally lacks DeleteObjectVersion so retained evidence
  # cannot be permanently erased by an application task.

  statement {
    sid       = "ListTransientDirectUploads"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.transient_uploads.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "${var.environment}/direct-uploads",
        "${var.environment}/direct-uploads/*",
      ]
    }
  }

  statement {
    sid       = "ListTransientMultipartUploads"
    effect    = "Allow"
    actions   = ["s3:ListBucketMultipartUploads"]
    resources = [aws_s3_bucket.transient_uploads.arn]
  }

  statement {
    sid    = "CleanTransientDirectUploads"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.transient_uploads.arn}/${var.environment}/direct-uploads/*",
    ]
  }

  statement {
    sid    = "UseObjectEncryptionKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey*",
      "kms:ReEncrypt*",
    ]
    resources = [aws_kms_key.main.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.${data.aws_partition.current.dns_suffix}"]
    }
  }
}

resource "aws_iam_role_policy" "object_store_task" {
  for_each = toset(["api", "worker"])

  name   = "environment-object-store"
  role   = aws_iam_role.task[each.value].id
  policy = data.aws_iam_policy_document.object_store_task.json
}

data "aws_iam_policy_document" "vpc_flow_assume" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.${data.aws_partition.current.dns_suffix}"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_iam_role" "vpc_flow" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  name               = "${local.name}-vpc-flow"
  assume_role_policy = data.aws_iam_policy_document.vpc_flow_assume[0].json
}

data "aws_iam_policy_document" "vpc_flow" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.vpc_flow[0].arn}:*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "vpc_flow" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  name   = "write-vpc-flow-log"
  role   = aws_iam_role.vpc_flow[0].id
  policy = data.aws_iam_policy_document.vpc_flow[0].json
}

resource "aws_flow_log" "vpc" {
  count = var.enable_vpc_flow_logs ? 1 : 0

  iam_role_arn    = aws_iam_role.vpc_flow[0].arn
  log_destination = aws_cloudwatch_log_group.vpc_flow[0].arn
  traffic_type    = "ALL"
  vpc_id          = aws_vpc.main.id

  max_aggregation_interval = 60
  log_format = join(" ", [
    "$${version}",
    "$${account-id}",
    "$${interface-id}",
    "$${srcaddr}",
    "$${dstaddr}",
    "$${srcport}",
    "$${dstport}",
    "$${protocol}",
    "$${packets}",
    "$${bytes}",
    "$${start}",
    "$${end}",
    "$${action}",
    "$${log-status}",
    "$${flow-direction}",
    "$${traffic-path}",
  ])
}
