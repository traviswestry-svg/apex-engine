terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.5" }
  }
}
provider "aws" { region = var.aws_region }
variable "aws_region" { type = string; default = "us-east-1" }
variable "bucket_name" { type = string; description = "Globally unique bucket in independent trust account" }
variable "render_service_id" { type = string; default = "srv-d7p3u2navr4c73d2q0jg" }
variable "observer_secret_arn" { type = string; description = "Existing Secrets Manager secret ARN with observer Render API token" }
variable "attestor_secret_arn" { type = string; description = "Existing *different* Secrets Manager secret ARN with attestor Render API token" }
variable "retention_days" { type = number; default = 30; validation { condition = var.retention_days >= 7; error_message = "At least 7 days." } }
variable "schedule_expression" { type = string; default = "rate(15 minutes)" }
variable "enable_deployment" { type = bool; default = false; description = "Explicit operator approval. Keep false for review." }

locals { count = var.enable_deployment ? 1 : 0 }

data "archive_file" "worker" {
  type = "zip"
  source_dir = "${path.module}/../worker_src"
  output_path = "${path.module}/worker.zip"
}

resource "aws_s3_bucket" "evidence" {
  count = local.count
  bucket = var.bucket_name
  object_lock_enabled = true
  force_destroy = false
}
resource "aws_s3_bucket_versioning" "evidence" {
  count = local.count
  bucket = aws_s3_bucket.evidence[0].id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  count = local.count
  bucket = aws_s3_bucket.evidence[0].id
  rule { default_retention { mode = "COMPLIANCE"; days = var.retention_days } }
  depends_on = [aws_s3_bucket_versioning.evidence]
}
resource "aws_s3_bucket_public_access_block" "evidence" {
  count = local.count
  bucket = aws_s3_bucket.evidence[0].id
  block_public_acls = true
  block_public_policy = true
  ignore_public_acls = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  count = local.count
  bucket = aws_s3_bucket.evidence[0].id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}
resource "aws_kms_key" "attestation" {
  count = local.count
  description = "APEX provider deployment attestation ONLY (not scanner identity)"
  key_usage = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
}
resource "aws_kms_alias" "attestation" {
  count = local.count
  name = "alias/apex-external-provider-attestation"
  target_key_id = aws_kms_key.attestation[0].key_id
}

data "aws_iam_policy_document" "assume_lambda" {
  statement { actions = ["sts:AssumeRole"]; principals { type = "Service"; identifiers = ["lambda.amazonaws.com"] } }
}
resource "aws_iam_role" "observer" {
  count = local.count
  name = "apex-external-observer"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}
resource "aws_iam_role" "attestor" {
  count = local.count
  name = "apex-external-attestor"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}
resource "aws_iam_role_policy_attachment" "observer_logs" {
  count = local.count
  role = aws_iam_role.observer[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy_attachment" "attestor_logs" {
  count = local.count
  role = aws_iam_role.attestor[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "observer" {
  count = local.count
  name = "read-secret-write-observations-only"
  role = aws_iam_role.observer[0].id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["secretsmanager:GetSecretValue"],Resource=[var.observer_secret_arn]},
    {Effect="Allow",Action=["s3:PutObject"],Resource=["${aws_s3_bucket.evidence[0].arn}/observations/*"]}
  ]})
}
resource "aws_iam_role_policy" "attestor" {
  count = local.count
  name = "read-secret-read-observations-sign-write-attestations"
  role = aws_iam_role.attestor[0].id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["secretsmanager:GetSecretValue"],Resource=[var.attestor_secret_arn]},
    {Effect="Allow",Action=["s3:GetObject"],Resource=["${aws_s3_bucket.evidence[0].arn}/observations/*"]},
    {Effect="Allow",Action=["s3:PutObject"],Resource=["${aws_s3_bucket.evidence[0].arn}/attestations/*"]},
    {Effect="Allow",Action=["kms:Sign","kms:GetPublicKey"],Resource=[aws_kms_key.attestation[0].arn]}
  ]})
}
resource "aws_lambda_function" "observer" {
  count = local.count
  function_name = "apex-independent-render-observer"
  filename = data.archive_file.worker.output_path
  source_code_hash = data.archive_file.worker.output_base64sha256
  runtime = "python3.12"
  handler = "lambda_package.trust_worker.observer_handler"
  role = aws_iam_role.observer[0].arn
  timeout = 90
  memory_size = 256
  environment { variables = {
    APEX_RENDER_SERVICE_ID = var.render_service_id
    EVIDENCE_BUCKET = aws_s3_bucket.evidence[0].id
    OBSERVER_RENDER_SECRET_ARN = var.observer_secret_arn
  } }
}
resource "aws_lambda_function" "attestor" {
  count = local.count
  function_name = "apex-independent-provider-attestor"
  filename = data.archive_file.worker.output_path
  source_code_hash = data.archive_file.worker.output_base64sha256
  runtime = "python3.12"
  handler = "lambda_package.trust_worker.attestor_handler"
  role = aws_iam_role.attestor[0].arn
  timeout = 90
  memory_size = 256
  environment { variables = {
    APEX_RENDER_SERVICE_ID = var.render_service_id
    EVIDENCE_BUCKET = aws_s3_bucket.evidence[0].id
    ATTESTOR_RENDER_SECRET_ARN = var.attestor_secret_arn
    ATTESTATION_KMS_KEY_ARN = aws_kms_key.attestation[0].arn
  } }
}
resource "aws_cloudwatch_event_rule" "observer" {
  count = local.count
  name = "apex-provider-observation-schedule"
  schedule_expression = var.schedule_expression
}
resource "aws_cloudwatch_event_target" "observer" {
  count = local.count
  rule = aws_cloudwatch_event_rule.observer[0].name
  arn = aws_lambda_function.observer[0].arn
}
resource "aws_lambda_permission" "schedule" {
  count = local.count
  statement_id = "AllowScheduledObservation"
  action = "lambda:InvokeFunction"
  function_name = aws_lambda_function.observer[0].function_name
  principal = "events.amazonaws.com"
  source_arn = aws_cloudwatch_event_rule.observer[0].arn
}
resource "aws_lambda_permission" "s3" {
  count = local.count
  statement_id = "AllowNewObservationEvent"
  action = "lambda:InvokeFunction"
  function_name = aws_lambda_function.attestor[0].function_name
  principal = "s3.amazonaws.com"
  source_arn = aws_s3_bucket.evidence[0].arn
  source_account = data.aws_caller_identity.current.account_id
}
data "aws_caller_identity" "current" {}
resource "aws_s3_bucket_notification" "new_observation" {
  count = local.count
  bucket = aws_s3_bucket.evidence[0].id
  lambda_function {
    lambda_function_arn = aws_lambda_function.attestor[0].arn
    events = ["s3:ObjectCreated:Put"]
    filter_prefix = "observations/"
    filter_suffix = ".json"
  }
  depends_on = [aws_lambda_permission.s3]
}
output "evidence_bucket" { value = var.enable_deployment ? aws_s3_bucket.evidence[0].id : "NOT_DEPLOYED" }
output "signing_key_arn" { value = var.enable_deployment ? aws_kms_key.attestation[0].arn : "NOT_DEPLOYED" }
output "production_activation_authorized" { value = false }
