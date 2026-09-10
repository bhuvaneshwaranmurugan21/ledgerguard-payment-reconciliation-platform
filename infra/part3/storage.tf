resource "aws_s3_bucket" "workload" {
  bucket        = local.bucket
  force_destroy = false
  tags          = local.tags
}

resource "aws_s3_bucket_ownership_controls" "workload" {
  bucket = aws_s3_bucket.workload.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "workload" {
  bucket                  = aws_s3_bucket.workload.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "workload" {
  bucket = aws_s3_bucket.workload.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "workload" {
  bucket = aws_s3_bucket.workload.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_policy" "workload" {
  bucket = aws_s3_bucket.workload.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.workload.arn, "${aws_s3_bucket.workload.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "workload" {
  bucket     = aws_s3_bucket.workload.id
  depends_on = [aws_s3_bucket_versioning.workload]
  rule {
    id     = "AbortIncompleteUploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  rule {
    id     = "ExpireEphemeralRuns"
    status = "Enabled"
    filter { prefix = "runs/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
  rule {
    id     = "ExpireGlueTemporaryData"
    status = "Enabled"
    filter { prefix = "temporary/glue/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
  rule {
    id     = "ExpireQueryResults"
    status = "Enabled"
    filter { prefix = "query-results/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
}

resource "aws_dynamodb_table" "control" {
  name         = "${local.name}-control"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  tags = local.tags
}
