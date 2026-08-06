resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name}-igw"
  }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.selected_availability_zones[count.index]
  cidr_block              = var.public_subnet_cidrs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name}-public-${count.index + 1}"
    Tier = "public-fargate"
  }
}

resource "aws_subnet" "private" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.selected_availability_zones[count.index]
  cidr_block              = var.private_subnet_cidrs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name}-private-${count.index + 1}"
    Tier = "private-data-and-cloudfront-origin"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name}-public"
  }
}

resource "aws_route" "public_ipv4" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Deliberately has only the implicit local route. RDS and ElastiCache never get
# a path to an internet gateway or NAT gateway.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name}-private-no-egress"
  }
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Private ALB ingress from this VPC's CloudFront VPC-origin service SG only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-alb"
  }
}

resource "aws_security_group" "frontend" {
  name        = "${local.name}-frontend"
  description = "ProofShape frontend Fargate tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-frontend"
  }
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "ProofShape API Fargate tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-api"
  }
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "ProofShape worker Fargate tasks; no ingress"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-worker"
  }
}

resource "aws_security_group" "migration" {
  name        = "${local.name}-migration"
  description = "ProofShape one-shot migration tasks; no ingress"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-migration"
  }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "Private PostgreSQL ingress from API, worker, and migration tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-database"
  }
}

resource "aws_security_group" "cache" {
  name        = "${local.name}-cache"
  description = "Private Redis ingress from API and worker tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-cache"
  }
}

# CloudFront creates this account/VPC-specific service security group only
# after the VPC origin exists. Unlike the global origin-facing prefix list, it
# cannot be used by an arbitrary distribution in another AWS account.
data "aws_security_group" "cloudfront_vpc_origin_service" {
  vpc_id = aws_vpc.main.id

  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG"]
  }

  depends_on = [aws_cloudfront_vpc_origin.alb]
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront_vpc_origin" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Selected listener from this VPC's CloudFront VPC origin"
  from_port                    = var.cloudfront_origin_protocol_policy == "https-only" ? 443 : 80
  to_port                      = var.cloudfront_origin_protocol_policy == "https-only" ? 443 : 80
  ip_protocol                  = "tcp"
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origin_service.id
}

resource "aws_vpc_security_group_ingress_rule" "frontend_from_alb" {
  security_group_id            = aws_security_group.frontend.id
  description                  = "Next.js only from the origin ALB"
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "API only from the origin ALB"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_ingress_rule" "api_from_frontend" {
  security_group_id            = aws_security_group.api.id
  description                  = "Cloud Map API discovery from frontend tasks"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.frontend.id
}

resource "aws_vpc_security_group_ingress_rule" "database" {
  for_each = {
    api       = aws_security_group.api.id
    migration = aws_security_group.migration.id
    worker    = aws_security_group.worker.id
  }

  security_group_id            = aws_security_group.database.id
  description                  = "PostgreSQL from ${each.key} tasks"
  from_port                    = var.rds_port
  to_port                      = var.rds_port
  ip_protocol                  = "tcp"
  referenced_security_group_id = each.value
}

resource "aws_vpc_security_group_ingress_rule" "cache" {
  for_each = {
    api    = aws_security_group.api.id
    worker = aws_security_group.worker.id
  }

  security_group_id            = aws_security_group.cache.id
  description                  = "TLS Redis from ${each.key} tasks"
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  referenced_security_group_id = each.value
}

resource "aws_vpc_security_group_egress_rule" "alb_to_frontend" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Origin ALB to frontend targets"
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.frontend.id
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Origin ALB to API targets"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.api.id
}

locals {
  task_security_groups = {
    api       = aws_security_group.api.id
    frontend  = aws_security_group.frontend.id
    migration = aws_security_group.migration.id
    worker    = aws_security_group.worker.id
  }
}

# Public-IP Fargate tasks need direct HTTPS egress for ECR image pulls, ECS
# bootstrap, Secrets Manager, CloudWatch Logs, and explicitly allowed SaaS APIs.
resource "aws_vpc_security_group_egress_rule" "task_https" {
  for_each = local.task_security_groups

  security_group_id = each.value
  description       = "HTTPS bootstrap and application egress without NAT"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_udp" {
  for_each = local.task_security_groups

  security_group_id = each.value
  description       = "DNS to the VPC resolver"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_tcp" {
  for_each = local.task_security_groups

  security_group_id = each.value
  description       = "TCP DNS fallback to the VPC resolver"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "frontend_to_api" {
  security_group_id            = aws_security_group.frontend.id
  description                  = "Internal API via Cloud Map"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.api.id
}

resource "aws_vpc_security_group_egress_rule" "database" {
  for_each = {
    api       = aws_security_group.api.id
    migration = aws_security_group.migration.id
    worker    = aws_security_group.worker.id
  }

  security_group_id            = each.value
  description                  = "PostgreSQL to the private database"
  from_port                    = var.rds_port
  to_port                      = var.rds_port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.database.id
}

resource "aws_vpc_security_group_egress_rule" "cache" {
  for_each = {
    api    = aws_security_group.api.id
    worker = aws_security_group.worker.id
  }

  security_group_id            = each.value
  description                  = "TLS Redis to the private cache"
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.cache.id
}
