resource "aws_cloudwatch_log_group" "platform" {
  for_each          = local.log_names
  name              = each.value
  retention_in_days = 7
  tags              = local.tags
}

resource "aws_iam_role" "runtime" {
  for_each             = local.services
  name                 = "${local.name}-${each.key}"
  path                 = "/ledgerguard/"
  permissions_boundary = var.permissions_boundary_arns[each.key]
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = each.value }
    }]
  })
  tags = local.tags
}

resource "aws_glue_job" "reconciliation" {
  depends_on        = [aws_iam_role_policy.runtime, aws_cloudwatch_log_group.platform]
  name              = "${local.name}-reconciliation"
  role_arn          = aws_iam_role.runtime["glue"].arn
  glue_version      = "5.1"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 15
  max_retries       = 0
  execution_class   = "STANDARD"
  execution_property { max_concurrent_runs = 1 }
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${local.bucket}/${var.stage5_release.script_key}"
  }
  default_arguments = {
    "--additional-python-modules"             = "s3://${local.bucket}/${var.stage5_release.wheels_key}"
    "--python-modules-installer-option"       = "--no-index"
    "--enable-observability-metrics"          = "true"
    "--enable-metrics"                        = ""
    "--enable-s3-parquet-optimized-committer" = "true"
    "--custom-logGroup-prefix"                = "/${local.name}/glue"
    "--job-bookmark-option"                   = "job-bookmark-disable"
    "--TempDir"                               = "s3://${local.bucket}/temporary/glue/"
  }
  non_overridable_arguments = {
    "--release-manifest-sha256" = var.stage5_release.manifest_sha256
    "--runtime-source-commit"   = var.stage5_release.source_commit
    "--runtime-source-tree"     = var.stage5_release.source_tree
    "--runtime-package-sha256"  = var.stage5_release.runtime_package_sha256
    "--runtime-script-sha256"   = var.stage5_release.script_sha256
    "--runtime-wheels-sha256"   = var.stage5_release.wheels_sha256
  }
  tags = local.tags
}

resource "aws_lambda_function" "validator" {
  function_name                  = "${local.name}-validator"
  role                           = aws_iam_role.runtime["validator"].arn
  runtime                        = "python3.11"
  handler                        = "ledgerguard_control.validator.handler"
  filename                       = var.stage5_release.validator_zip
  source_code_hash               = var.stage5_release.validator_sha256_base64
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = 1
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKLOAD_BUCKET = local.bucket
      CONTROL_TABLE   = aws_dynamodb_table.control.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.platform, aws_iam_role_policy.runtime]
  tags       = local.tags
}

resource "aws_lambda_function" "controller" {
  function_name                  = "${local.name}-controller"
  role                           = aws_iam_role.runtime["controller"].arn
  runtime                        = "python3.11"
  handler                        = "ledgerguard_control.controller.handler"
  filename                       = var.stage5_release.controller_zip
  source_code_hash               = var.stage5_release.controller_sha256_base64
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = 1
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKLOAD_BUCKET = local.bucket
      CONTROL_TABLE   = aws_dynamodb_table.control.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.platform, aws_iam_role_policy.runtime]
  tags       = local.tags
}

resource "aws_sfn_state_machine" "reconciliation" {
  name       = "${local.name}-reconciliation"
  role_arn   = aws_iam_role.runtime["workflow"].arn
  type       = "STANDARD"
  definition = var.stage5_release.definition
  depends_on = [aws_iam_role_policy.runtime]
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.platform["workflow"].arn}:*"
    include_execution_data = false
    level                  = "ALL"
  }
  tags = local.tags
}
