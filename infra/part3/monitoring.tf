resource "aws_cloudwatch_metric_alarm" "control_errors" {
  for_each            = toset(["validator", "controller"])
  alarm_name          = "${local.name}-${each.value}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "missing"
  dimensions          = { FunctionName = "${local.name}-${each.value}" }
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "workflow_failure" {
  alarm_name          = "${local.name}-workflow-failure"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "missing"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.reconciliation.arn }
  tags                = local.tags
}
