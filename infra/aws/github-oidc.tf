resource "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_oidc && var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Name = "github-actions"
  }
}

data "aws_iam_policy_document" "github_deploy_assume" {
  count = var.enable_github_oidc ? 1 : 0

  statement {
    sid     = "ExactRepositoryEnvironment"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.github_oidc_subject]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count = var.enable_github_oidc ? 1 : 0

  name                 = "${local.name}-github-deploy"
  description          = "Exact-repository image publication and digest-only ECS promotion from ${var.github_repository} ${var.github_environment}"
  assume_role_policy   = data.aws_iam_policy_document.github_deploy_assume[0].json
  max_session_duration = var.github_oidc_max_session_seconds

  tags = {
    GitHubEnvironment = var.github_environment
    GitHubRepository  = var.github_repository
  }

  depends_on = [terraform_data.contract]
}

locals {
  ecs_service_arns = [
    for component in ["api", "frontend", "worker"] :
    "arn:${data.aws_partition.current.partition}:ecs:${var.aws_region}:${var.aws_account_id}:service/${aws_ecs_cluster.main.name}/${local.name}-${component}"
  ]

  ecs_migration_task_definition_arn = "arn:${data.aws_partition.current.partition}:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${local.name}-migration:*"
}

data "aws_iam_policy_document" "github_deploy" {
  count = var.enable_github_oidc ? 1 : 0

  statement {
    sid    = "VerifyBoundary"
    effect = "Allow"
    actions = [
      "ecs:DescribeClusters",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "GetEcrAuthorizationToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PushAndInspectExactReleaseRepositories"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }

  statement {
    sid       = "VerifySecretVersionsWithoutReadingValues"
    effect    = "Allow"
    actions   = ["secretsmanager:ListSecretVersionIds"]
    resources = values(local.runtime_secret_arns)
  }

  statement {
    sid    = "InspectDeploymentState"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "InspectMigrationNetwork"
    effect = "Allow"
    actions = [
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "RegisterDigestTaskDefinitions"
    effect    = "Allow"
    actions   = ["ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "UpdateExactServices"
    effect    = "Allow"
    actions   = ["ecs:UpdateService"]
    resources = local.ecs_service_arns
  }

  statement {
    sid       = "RunMigrationTask"
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = [local.ecs_migration_task_definition_arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    sid     = "PassOnlyProofShapeTaskRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = concat(
      [for role in aws_iam_role.execution : role.arn],
      [for role in aws_iam_role.task : role.arn],
    )

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.${data.aws_partition.current.dns_suffix}"]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  count = var.enable_github_oidc ? 1 : 0

  name   = "exact-image-publish-and-digest-promotion"
  role   = aws_iam_role.github_deploy[0].id
  policy = data.aws_iam_policy_document.github_deploy[0].json
}
