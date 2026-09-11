locals {
  catalog = jsondecode(file("${path.module}/../../spec/part3-stage4-catalog-v1.json"))
}

resource "aws_glue_catalog_database" "reconciliation" {
  name       = replace("${local.name}-reconciliation", "-", "_")
  catalog_id = "857229544428"
}

resource "aws_glue_catalog_table" "candidate" {
  for_each      = local.catalog.tables
  name          = each.key
  database_name = aws_glue_catalog_database.reconciliation.name
  catalog_id    = "857229544428"
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL                     = "TRUE"
    classification               = "parquet"
    "projection.enabled"         = "true"
    "projection.run_id.type"     = "injected"
    "projection.attempt_id.type" = "injected"
    "storage.location.template"  = "s3://${local.bucket}/runs/$${run_id}/attempts/$${attempt_id}/candidates/${replace(each.key, "_", "-")}/"
  }
  partition_keys {
    name = "run_id"
    type = "string"
  }
  partition_keys {
    name = "attempt_id"
    type = "string"
  }
  storage_descriptor {
    location      = "s3://${local.bucket}/catalog-unselected/${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }
    dynamic "columns" {
      for_each = each.value
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

resource "aws_athena_workgroup" "reconciliation" {
  name          = "${local.name}-checks"
  state         = "ENABLED"
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 104857600
    publish_cloudwatch_metrics_enabled = true
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location       = "s3://${local.bucket}/query-results/"
      expected_bucket_owner = "857229544428"
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
  tags = local.tags
}
