output "db_endpoint" {
  value       = aws_db_instance.this.endpoint
  description = "RDS Postgres endpoint (host:port)."
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "documents_bucket" {
  value       = aws_s3_bucket.documents.bucket
  description = "S3 bucket for raw uploaded documents."
}

output "kms_key_arn" {
  value       = aws_kms_key.this.arn
  description = "KMS key used for RDS + S3 encryption."
}
