# Example production values. Replace network IDs with real ones before applying.
region                 = "us-east-1"
name_prefix            = "docintake-production"
vpc_id                 = "vpc-REPLACE"
private_subnet_ids     = ["subnet-REPLACE-a", "subnet-REPLACE-b", "subnet-REPLACE-c"]
app_security_group_ids = ["sg-REPLACE-app"]

db_instance_class       = "db.r6g.large"
db_allocated_storage    = 100
multi_az                = true
backup_retention_period = 30
deletion_protection     = true
skip_final_snapshot     = false
# db_password supplied via TF_VAR_db_password (never commit secrets).
