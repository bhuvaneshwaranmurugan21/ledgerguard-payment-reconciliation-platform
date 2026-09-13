locals {
  bucket_arn = "arn:aws:s3:::${local.bucket}"
  # Predictable names keep IAM policy creation ahead of compute creation without
  # introducing a policy -> function/job -> policy dependency cycle.
  control_arn   = "arn:aws:dynamodb:ap-southeast-2:857229544428:table/${local.name}-control"
  glue_arn      = "arn:aws:glue:ap-southeast-2:857229544428:job/${local.name}-reconciliation"
  workgroup_arn = "arn:aws:athena:ap-southeast-2:857229544428:workgroup/${local.name}-checks"
  function_arns = { for role in ["validator", "controller"] : role => "arn:aws:lambda:ap-southeast-2:857229544428:function:${local.name}-${role}" }
  catalog_arns = [
    "arn:aws:glue:ap-southeast-2:857229544428:catalog",
    "arn:aws:glue:ap-southeast-2:857229544428:database/${replace("${local.name}-reconciliation", "-", "_")}",
    "arn:aws:glue:ap-southeast-2:857229544428:table/${replace("${local.name}-reconciliation", "-", "_")}/transactions",
    "arn:aws:glue:ap-southeast-2:857229544428:table/${replace("${local.name}-reconciliation", "-", "_")}/settlements",
    "arn:aws:glue:ap-southeast-2:857229544428:table/${replace("${local.name}-reconciliation", "-", "_")}/bank_allocations"
  ]
  runtime_statements = {
    glue = [
      {
        Sid    = "ReadExactDeploymentAndRunInputs", Effect = "Allow"
        Action = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = [
          "${local.bucket_arn}/${var.stage5_release.script_key}",
          "${local.bucket_arn}/${var.stage5_release.wheels_key}",
          "${local.bucket_arn}/runs/*/inputs/*"
        ]
      },
      {
        Sid      = "WriteNonAuthoritativeCandidates", Effect = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = ["${local.bucket_arn}/runs/*/attempts/*/candidates/*", "${local.bucket_arn}/temporary/glue/*"]
      },
      {
        Sid      = "ReadBackCandidates", Effect = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${local.bucket_arn}/runs/*/attempts/*/candidates/*", "${local.bucket_arn}/temporary/glue/*"]
      },
      {
        Sid       = "ListBoundedRunAndTemporaryPrefixes", Effect = "Allow"
        Action    = ["s3:ListBucket"], Resource = [local.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = ["runs/*/inputs/*", "runs/*/attempts/*/candidates/*", "temporary/glue/*"] } }
      },
      {
        Sid    = "RemoveCommitterTemporaryObjectsOnly", Effect = "Allow"
        Action = ["s3:DeleteObject"]
        Resource = [
          "${local.bucket_arn}/runs/*/attempts/*/candidates/*/_temporary/*",
          "${local.bucket_arn}/temporary/glue/*"
        ]
      },
      {
        Sid    = "LocateWorkloadBucket", Effect = "Allow"
        Action = ["s3:GetBucketLocation"], Resource = [local.bucket_arn]
      },
      {
        Sid       = "GlueObservability", Effect = "Allow"
        Action    = ["cloudwatch:PutMetricData"], Resource = ["*"]
        Condition = { StringEquals = { "cloudwatch:namespace" = "Glue" } }
      }
    ]
    validator = [
      {
        Sid      = "ReadRunAndPublicationEvidence", Effect = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${local.bucket_arn}/runs/*", "${local.bucket_arn}/publications/*", "${local.bucket_arn}/query-results/*"]
      },
      {
        Sid       = "InventoryRunVersions", Effect = "Allow"
        Action    = ["s3:ListBucket", "s3:ListBucketVersions"], Resource = [local.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = ["runs/*", "publications/*", "query-results/*"] } }
      },
      {
        Sid      = "ReadAuthorityOnly", Effect = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query"]
        Resource = [local.control_arn]
      },
      {
        Sid      = "InspectBoundedQueries", Effect = "Allow"
        Action   = ["athena:GetQueryExecution", "athena:GetQueryResults"]
        Resource = [local.workgroup_arn]
      },
      {
        Sid      = "InspectActualGlueRun", Effect = "Allow"
        Action   = ["glue:GetJobRun"]
        Resource = [local.glue_arn]
      }
    ]
    controller = [
      {
        Sid      = "ReadValidatedRunAndPublicationEvidence", Effect = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${local.bucket_arn}/runs/*", "${local.bucket_arn}/publications/*"]
      },
      {
        Sid      = "PrepareImmutableBodiesAndFailureEvidence", Effect = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${local.bucket_arn}/publications/*", "${local.bucket_arn}/runs/*/attempts/*/evidence/*"]
      },
      {
        Sid      = "ConditionalControlMetadata", Effect = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem", "dynamodb:TransactWriteItems"]
        Resource = [local.control_arn]
      }
    ]
    workflow = [
      {
        Sid      = "BoundedGlueIntegration", Effect = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
        Resource = [local.glue_arn]
      },
      {
        Sid      = "BoundedAthenaIntegration", Effect = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution"]
        Resource = [local.workgroup_arn]
      },
      {
        Sid      = "CatalogReadOnly", Effect = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
        Resource = local.catalog_arns
      },
      {
        Sid      = "QueryReadCandidates", Effect = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${local.bucket_arn}/runs/*/attempts/*/candidates/*", "${local.bucket_arn}/query-results/*"]
      },
      {
        Sid      = "QueryWriteResults", Effect = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = ["${local.bucket_arn}/query-results/*"]
      },
      {
        Sid       = "QueryListPrefixes", Effect = "Allow"
        Action    = ["s3:ListBucket"], Resource = [local.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = ["runs/*/attempts/*/candidates/*", "query-results/*"] } }
      },
      {
        Sid    = "QueryBucketLocation", Effect = "Allow"
        Action = ["s3:GetBucketLocation"], Resource = [local.bucket_arn]
      },
      {
        Sid      = "InvokeExactControlFunctions", Effect = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [local.function_arns["validator"], local.function_arns["controller"]]
      },
      {
        Sid      = "StepFunctionsLogDelivery", Effect = "Allow"
        Action   = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
        Resource = ["*"]
      }
    ]
  }
  role_log_keys = {
    glue       = ["glue_error", "glue_output"]
    validator  = ["validator"]
    controller = ["controller"]
    workflow   = []
  }
}

# These are workload identities only. The GitHub deployment/rescue identities and
# administrator boundary are deliberately outside this Terraform state.
resource "aws_iam_role_policy" "runtime" {
  for_each = local.services
  name     = "${local.name}-${each.key}"
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.runtime_statements[each.key], length(local.role_log_keys[each.key]) > 0 ? [{
      Sid      = "WriteOwnStructuredLogs", Effect = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [for name in local.role_log_keys[each.key] : "${aws_cloudwatch_log_group.platform[name].arn}:*"]
      }] : [], contains(["validator", "controller"], each.key) ? [{
      Sid       = "LambdaTraceTelemetry", Effect = "Allow"
      Action    = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = ["*"]
      Condition = { StringEquals = { "aws:RequestedRegion" = "ap-southeast-2" } }
    }] : [])
  })
}
