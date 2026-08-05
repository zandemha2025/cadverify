resource "aws_lb" "origin" {
  name               = local.name
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.private[*].id

  enable_deletion_protection = var.alb_deletion_protection
  drop_invalid_header_fields = true
  desync_mitigation_mode     = "strictest"
  idle_timeout               = 300
  preserve_host_header       = true

  dynamic "access_logs" {
    for_each = var.alb_access_log_bucket_name == "" ? [] : [var.alb_access_log_bucket_name]

    content {
      bucket  = access_logs.value
      enabled = true
      prefix  = "${var.project_name}/${var.environment}/alb"
    }
  }

  tags = {
    Name             = "${local.name}-cloudfront-origin"
    PublicReleaseUrl = "false"
    Reachability     = "cloudfront-vpc-origin-only"
  }
}

resource "aws_lb_target_group" "frontend" {
  name        = "${substr(local.name, 0, 26)}-web"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 60

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200-399"
    path                = "/"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 10
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${substr(local.name, 0, 26)}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 120

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 10
    unhealthy_threshold = 3
  }
}

# The listener defaults to a fixed 403. Explicit path rules are the only
# forwarding actions, and the ALB security group accepts traffic only from the
# CloudFront VPC-origin service security group created in this VPC.
resource "aws_lb_listener" "origin_http" {
  count = var.cloudfront_origin_protocol_policy == "http-only" ? 1 : 0

  load_balancer_arn = aws_lb.origin.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener" "origin_https" {
  count = var.cloudfront_origin_protocol_policy == "https-only" ? 1 : 0

  load_balancer_arn = aws_lb.origin.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.alb_origin_acm_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "forbidden"
      status_code  = "403"
    }
  }
}

locals {
  origin_listener_arn = (
    var.cloudfront_origin_protocol_policy == "https-only" ?
    aws_lb_listener.origin_https[0].arn :
    aws_lb_listener.origin_http[0].arn
  )
}

resource "aws_lb_listener_rule" "api_primary_paths" {
  listener_arn = local.origin_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/api/v1",
        "/api/v1/*",
        "/auth",
        "/auth/*",
        "/health*",
      ]
    }
  }
}

resource "aws_lb_listener_rule" "api_secondary_paths" {
  listener_arn = local.origin_listener_arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/metrics",
        "/s/*",
        "/scim/v2/*",
      ]
    }
  }
}

resource "aws_lb_listener_rule" "frontend_all_paths" {
  listener_arn = local.origin_listener_arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }
}

# A VPC origin is the origin-verification contract. The ALB has no public IP,
# and only the account/VPC-specific CloudFront service security group can open
# its listener. This is stronger than a shared managed prefix list plus a
# reusable secret header, while keeping all secret values out of Terraform.
resource "aws_cloudfront_vpc_origin" "alb" {
  vpc_origin_endpoint_config {
    name                   = "${local.name}-alb"
    arn                    = aws_lb.origin.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = var.cloudfront_origin_protocol_policy

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  tags = {
    Name = "${local.name}-alb-origin"
  }

  depends_on = [
    aws_lb_listener_rule.api_primary_paths,
    aws_lb_listener_rule.api_secondary_paths,
    aws_lb_listener_rule.frontend_all_paths,
  ]
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Dynamic requests retain every viewer header/cookie/query parameter and add
# the one CloudFront-generated client address header accepted by ProofShape's
# AWS auth-proxy mode. The application never trusts the ALB X-Forwarded-For
# chain for this deployment.
resource "aws_cloudfront_origin_request_policy" "dynamic" {
  name    = "${local.name}-dynamic"
  comment = "All viewer values plus CloudFront-Viewer-Address"

  cookies_config {
    cookie_behavior = "all"
  }

  headers_config {
    header_behavior = "allViewerAndWhitelistCloudFront"

    headers {
      items = ["CloudFront-Viewer-Address"]
    }
  }

  query_strings_config {
    query_string_behavior = "all"
  }
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${local.name}-security"
  comment = "Viewer security headers; application headers may be stricter"

  security_headers_config {
    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = false
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = false
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      override                   = true
      preload                    = false
    }

    xss_protection {
      mode_block = true
      override   = true
      protection = true
    }
  }
}

resource "aws_cloudwatch_log_group" "waf" {
  count    = var.enable_waf_logging ? 1 : 0
  provider = aws.us_east_1

  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_wafv2_web_acl" "cloudfront" {
  count    = var.enable_waf ? 1 : 0
  provider = aws.us_east_1

  name        = local.name
  description = "ProofShape commercial CloudFront baseline"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  dynamic "rule" {
    for_each = var.cloudfront_alias == "" ? [] : [var.cloudfront_alias]
    iterator = canonical_alias

    content {
      name     = "canonical-host-only"
      priority = 1

      action {
        block {}
      }

      statement {
        not_statement {
          statement {
            byte_match_statement {
              positional_constraint = "EXACTLY"
              search_string         = canonical_alias.value

              field_to_match {
                single_header {
                  name = "host"
                }
              }

              text_transformation {
                priority = 0
                type     = "LOWERCASE"
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.name}-canonical-host"
        sampled_requests_enabled   = true
      }
    }
  }

  rule {
    name     = "aws-common"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # ProofShape legitimately streams large multipart CAD bodies. Keep the
        # header/query protections, but do not let generic 8 KiB body limits or
        # body-XSS heuristics reject those uploads before application controls.
        rule_action_override {
          name = "SizeRestrictions_BODY"

          action_to_use {
            count {}
          }
        }

        rule_action_override {
          name = "CrossSiteScripting_BODY"

          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-known-bad"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 30

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "viewer-rate-limit"
    priority = 40

    action {
      block {}
    }

    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.waf_rate_limit
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "cloudfront" {
  count    = var.enable_waf_logging ? 1 : 0
  provider = aws.us_east_1

  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]
  resource_arn            = aws_wafv2_web_acl.cloudfront[0].arn

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }

  redacted_fields {
    single_header {
      name = "cookie"
    }
  }

  # OAuth/OIDC callbacks and other application routes can carry short-lived
  # credentials in the query string. Keep paths/statuses for incident response
  # without persisting those values in WAF records.
  redacted_fields {
    query_string {}
  }
}

resource "aws_cloudfront_distribution" "app" {
  enabled             = true
  comment             = "ProofShape ${var.environment} canonical HTTPS release edge"
  aliases             = var.cloudfront_alias == "" ? [] : [var.cloudfront_alias]
  default_root_object = ""
  http_version        = "http2and3"
  is_ipv6_enabled     = var.cloudfront_ipv6_enabled
  price_class         = var.cloudfront_price_class
  retain_on_delete    = var.cloudfront_retain_on_delete
  wait_for_deployment = var.cloudfront_wait_for_deployment
  web_acl_id          = var.enable_waf ? aws_wafv2_web_acl.cloudfront[0].arn : null

  origin {
    domain_name = aws_lb.origin.dns_name
    origin_id   = "proofshape-alb-origin"

    vpc_origin_config {
      vpc_origin_id            = aws_cloudfront_vpc_origin.alb.id
      origin_keepalive_timeout = 60
      origin_read_timeout      = 60
    }
  }

  default_cache_behavior {
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    compress                   = true
    origin_request_policy_id   = aws_cloudfront_origin_request_policy.dynamic.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    target_origin_id           = "proofshape-alb-origin"
    viewer_protocol_policy     = "redirect-to-https"
  }

  dynamic "ordered_cache_behavior" {
    for_each = toset([
      "/api/*",
      "/auth/*",
      "/health*",
      "/s/*",
      "/scim/*",
    ])

    content {
      path_pattern               = ordered_cache_behavior.value
      allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
      compress                   = true
      origin_request_policy_id   = aws_cloudfront_origin_request_policy.dynamic.id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
      target_origin_id           = "proofshape-alb-origin"
      viewer_protocol_policy     = "redirect-to-https"
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.enable_static_asset_caching ? ["/_next/static/*"] : []

    content {
      path_pattern               = ordered_cache_behavior.value
      allowed_methods            = ["GET", "HEAD", "OPTIONS"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
      compress                   = true
      origin_request_policy_id   = aws_cloudfront_origin_request_policy.dynamic.id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
      target_origin_id           = "proofshape-alb-origin"
      viewer_protocol_policy     = "redirect-to-https"
    }
  }

  dynamic "logging_config" {
    for_each = var.cloudfront_access_log_bucket_domain == "" ? [] : [var.cloudfront_access_log_bucket_domain]

    content {
      bucket          = logging_config.value
      include_cookies = false
      prefix          = "${var.project_name}/${var.environment}/cloudfront/"
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn            = var.cloudfront_alias == "" ? null : var.cloudfront_acm_certificate_arn
    cloudfront_default_certificate = var.cloudfront_alias == ""
    minimum_protocol_version       = var.cloudfront_alias == "" ? "TLSv1" : "TLSv1.2_2021"
    ssl_support_method             = var.cloudfront_alias == "" ? null : "sni-only"
  }

  tags = {
    Name                = "${local.name}-release-edge"
    CanonicalReleaseUrl = "true"
  }

  depends_on = [
    aws_vpc_security_group_ingress_rule.alb_from_cloudfront_vpc_origin,
    terraform_data.contract,
  ]
}

locals {
  canonical_public_hostname = var.cloudfront_alias != "" ? var.cloudfront_alias : aws_cloudfront_distribution.app.domain_name
  canonical_public_origin   = "https://${local.canonical_public_hostname}"
}

resource "aws_route53_record" "cloudfront_ipv4" {
  count = var.cloudfront_alias != "" && var.route53_zone_id != "" ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.cloudfront_alias
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.app.domain_name
    zone_id                = aws_cloudfront_distribution.app.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "cloudfront_ipv6" {
  count = var.cloudfront_alias != "" && var.route53_zone_id != "" && var.cloudfront_ipv6_enabled ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.cloudfront_alias
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.app.domain_name
    zone_id                = aws_cloudfront_distribution.app.hosted_zone_id
    evaluate_target_health = false
  }
}
