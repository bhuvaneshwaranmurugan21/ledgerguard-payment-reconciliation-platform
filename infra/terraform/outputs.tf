output "feeds_bucket" {
  value = aws_s3_bucket.feeds.id
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.id
}

output "case_table" {
  value = aws_dynamodb_table.cases.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.reconciliation.arn
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.workflow.name
}

