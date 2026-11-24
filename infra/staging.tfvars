# Example staging values. Replace network IDs with real ones before applying.
region                 = "us-east-1"
name_prefix            = "docintake-staging"
vpc_id                 = "vpc-REPLACE"
private_subnet_ids     = ["subnet-REPLACE-a", "subnet-REPLACE-b"]
app_security_group_ids = ["sg-REPLACE-app"]

db_instance_class   = "db.t4g.micro"
multi_az            = false
deletion_protection = false
skip_final_snapshot = true
# db_password supplied via TF_VAR_db_password (never commit secrets).
