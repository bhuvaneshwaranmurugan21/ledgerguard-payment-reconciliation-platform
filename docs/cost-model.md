# Cost controls

- Small synthetic feeds and one bounded orchestration run.
- S3 inputs/evidence and DynamoDB cases use inexpensive serverless capacity.
- No NAT gateway, MSK, or permanent compute cluster.
- CloudWatch logs expire after seven days.
- Run/expiry tags and verified destroy are part of the experiment.
- Measured cost is required by the AWS evidence validator.

Estimated and actual cost remain separate fields; architecture does not prove spend.

