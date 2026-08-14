data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name   = "ledgerguard-${var.environment}"
  prefix = "${local.name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  tags = {
    Project     = "LedgerGuard"
    RunId       = var.run_id
    Environment = var.environment
    ExpiresAt   = var.expires_at
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket" "feeds" {
  bucket        = "${local.prefix}-feeds"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket" "evidence" {
  bucket        = "${local.prefix}-evidence"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket_versioning" "feeds" {
  bucket = aws_s3_bucket.feeds.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "feeds" {
  bucket                  = aws_s3_bucket.feeds.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "feeds" {
  bucket = aws_s3_bucket.feeds.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_glue_catalog_database" "reconciliation" {
  name = replace(local.name, "-", "_")
}

resource "aws_dynamodb_table" "cases" {
  name         = "${local.name}-cases"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "payment_id"

  attribute {
    name = "payment_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_cloudwatch_log_group" "workflow" {
  name              = "/aws/ledgerguard/${var.run_id}"
  retention_in_days = 7
}

resource "aws_iam_role" "states" {
  name = "${local.name}-states-${random_id.suffix.hex}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "states_logs" {
  role = aws_iam_role.states.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogDelivery",
        "logs:GetLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries",
        "logs:PutResourcePolicy",
        "logs:DescribeResourcePolicies",
        "logs:DescribeLogGroups"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_sfn_state_machine" "reconciliation" {
  name     = "${local.name}-reconciliation-${random_id.suffix.hex}"
  role_arn = aws_iam_role.states.arn

  logging_configuration {
    include_execution_data = true
    level                  = "ALL"
    log_destination        = "${aws_cloudwatch_log_group.workflow.arn}:*"
  }

  definition = jsonencode({
    Comment = "Control contract; managed job adapters are attached only in an AWS-verified run"
    StartAt = "ValidateManifest"
    States = {
      ValidateManifest = { Type = "Pass", Next = "Reconcile" }
      Reconcile        = { Type = "Pass", Next = "SettlementGate" }
      SettlementGate = {
        Type = "Choice"
        Choices = [{
          Variable      = "$.matched"
          BooleanEquals = true
          Next          = "Matched"
        }]
        Default = "Exception"
      }
      Matched   = { Type = "Succeed" }
      Exception = { Type = "Fail", Error = "SettlementMismatch" }
    }
  })
}

