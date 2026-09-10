variable "operation_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{7,31}$", var.operation_id))
    error_message = "Use an immutable 8–32 character operation identity."
  }
}

variable "expires_at" {
  type = string
  validation {
    condition     = can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", var.expires_at))
    error_message = "An explicit RFC3339 expiry is required."
  }
}

variable "permissions_boundary_arns" {
  type = map(string)
  validation {
    condition = (
      toset(keys(var.permissions_boundary_arns)) == toset(["glue", "workflow", "validator", "controller"]) &&
      alltrue([for role, arn in var.permissions_boundary_arns : arn == "arn:aws:iam::857229544428:policy/LedgerGuardPart3-${role}-Boundary-v1"])
    )
    error_message = "Each runtime identity requires its exact administrator-owned boundary."
  }
}

# Stage 5 supplies real qualified artifacts and definition. There are no defaults,
# dummy archives, placeholder success definitions, or deployment eligibility here.
variable "stage5_release" {
  type = object({
    definition               = string
    definition_sha256        = string
    validator_zip            = string
    validator_sha256_base64  = string
    controller_zip           = string
    controller_sha256_base64 = string
    script_key               = string
    wheels_key               = string
  })
  validation {
    condition = (
      sha256(var.stage5_release.definition) == var.stage5_release.definition_sha256 &&
      try(jsondecode(var.stage5_release.definition).TimeoutSeconds, 0) == 1800 &&
      can(jsondecode(var.stage5_release.definition).States[jsondecode(var.stage5_release.definition).StartAt]) &&
      filebase64sha256(var.stage5_release.validator_zip) == var.stage5_release.validator_sha256_base64 &&
      filebase64sha256(var.stage5_release.controller_zip) == var.stage5_release.controller_sha256_base64 &&
      can(regex("^deployment/[0-9a-f]{64}/ledgerguard_stage3_job\\.py$", var.stage5_release.script_key)) &&
      can(regex("^deployment/[0-9a-f]{64}/ledgerguard\\.gluewheels\\.zip$", var.stage5_release.wheels_key))
    )
    error_message = "Real package bytes, bounded workflow and deployment objects must have exact identities."
  }
}

locals {
  name   = "ledgerguard-p3-${var.operation_id}"
  bucket = "ledgerguard-p3-857229544428-${var.operation_id}"
  tags   = { OperationId = var.operation_id, ExpiresAt = var.expires_at }
  services = {
    glue       = "glue.amazonaws.com"
    workflow   = "states.amazonaws.com"
    validator  = "lambda.amazonaws.com"
    controller = "lambda.amazonaws.com"
  }
  log_names = {
    glue_error  = "/${local.name}/glue/error"
    glue_output = "/${local.name}/glue/output"
    workflow    = "/aws/vendedlogs/states/${local.name}"
    validator   = "/aws/lambda/${local.name}-validator"
    controller  = "/aws/lambda/${local.name}-controller"
  }
}
