variable "region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. docintake-staging."
}

variable "vpc_id" {
  type        = string
  description = "VPC to place the database security group in."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for the RDS subnet group (no public route)."
}

variable "app_security_group_ids" {
  type        = list(string)
  default     = []
  description = "Security groups allowed to reach Postgres on 5432."
}

variable "db_name" {
  type    = string
  default = "docintake"
}

variable "db_username" {
  type    = string
  default = "app_user"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Master password. Supply via TF_VAR_db_password or a secrets manager."
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "backup_retention_period" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}
