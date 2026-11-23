# APEX Controlled External Trust Deployment — Operator-Reviewed Package

**State: BUILD_READY / NOT_DEPLOYED / NO_GO.** This package is separate from APEX. It creates infrastructure **only when an independent AWS account administrator explicitly applies Terraform with `enable_deployment=true`**. It must not be deployed into the APEX Render shell or alongside its writable `/data` disk.

## What is in the package

- `terraform/main.tf`: restricted AWS Lambda observer and attestor roles, scheduled collector, S3 Object Lock **COMPLIANCE** retention, server-side encryption, asymmetric AWS KMS P-256 signer, and S3 event notification.
- `worker_src/lambda_package/`: AWS Lambda Python 3.12 handlers. Collector reads Render API, captures current deployment ID + SHA to S3. Attestor has a **different** role/Render token and independently re-queries Render before signing a narrowly scoped deployment statement with non-exportable KMS key material.
- `verify_provider_attestation.py`: offline public-key-pinned ECDSA P-256 signature and observation-digest verifier. It never authenticates scanner process origin or grants GO.
- `tests/`: self-contained mock-based tests (not an AWS deployment test).

This differs from the earlier Phase 4B **Ed25519** research schema. Signatures produced by this package use **AWS KMS ECDSA_SHA_256** and must be checked by the included standalone verifier; do not feed them into the Phase 4B Ed25519 verifier without a separately audited protocol adapter.

## Deployment prerequisites and separation

1. Use a **separately administered AWS account**, ideally not controlled by APEX deploy credentials, operators, or the Render web service. AWS organization SCPs, CloudTrail delivered to another security account, and tightly restricted administrator access are additional requirements for a meaningful independent trust boundary; this Terraform alone cannot establish administrative independence.
2. Provision two **separate Render API credentials** authorized to read deployment metadata, where your Render account permissions support the separation. Create two independently controlled AWS Secrets Manager secrets containing the raw API tokens as `SecretString`. **Do not paste credentials into ChatGPT, Terraform files, CLI arguments, source control, Lambda environment values, or APEX.** The two secrets must exist before `terraform apply`; pass only ARNs.
3. Choose a globally unique AWS S3 bucket name. **Object Lock COMPLIANCE retention cannot be shortened or removed for locked object versions**, and costs are incurred after deployment. Review the 30-day default before approval.
4. Maintain Terraform state in a secure, encrypted, access-controlled backend managed by the independent operator. Never commit `.tfstate`, secret material, or key-derived credentials.
5. Review access rights: collector can write only `observations/*` and retrieve its own Render token; attestor can read observations, write attestations, retrieve its different token and use `kms:Sign`. Neither role may alter APEX resources or modify historical databases. Validate IAM with AWS IAM Access Analyzer before deployment.

## Test and review locally (no external credentials)

```bash
cd controlled_external_trust
PYTHONPATH=. python -m unittest discover -s tests -v
cd terraform
terraform init
terraform validate
terraform plan \
  -var='bucket_name=REPLACE_WITH_UNIQUE_NAME' \
  -var='observer_secret_arn=ARN_OF_INDEPENDENT_COLLECTOR_SECRET' \
  -var='attestor_secret_arn=ARN_OF_INDEPENDENT_ATTESTOR_SECRET'
# The default enable_deployment=false produces no new AWS resources.
```

**An operator with separate-account authority** can review a proposed deployment by setting `-var='enable_deployment=true'` in `terraform plan -out=reviewed.tfplan` and inspecting every resource and IAM permission. Deploy only with explicit change approval using `terraform apply reviewed.tfplan`. Do not set this flag in APEX, Render, or a development workstation that has APEX production secrets. The Terraform plan alone is not permission to deploy.

## AWS acceptance tests after independent deployment

1. Confirm AWS account/role separation; verify the two Lambda roles, secret ARNs, and KMS key ARN without copying secret values.
2. Verify S3 versioning and Object Lock COMPLIANCE configuration, actual per-object retention, default retention period, public-access blocking, and that the APEX Render service has **no S3/KMS permissions**.
3. Invoke the observer with `{}` (from the independent AWS account). Its first genuine output must include `OBSERVATION_STORED` and a `observations/srv-.../SHA256.json` S3 object containing a Render deployment identifier and 40-character Git SHA.
4. Verify the S3 notification invokes the attestor and writes a `attestations/srv-.../SHA256.json` object only after requery. Check error logging and retries, alarm policy, retention, and key access.
5. Obtain AWS KMS public key independently using `aws kms get-public-key` and convert its DER SubjectPublicKeyInfo to PEM with a trusted external tool. **Pin the resulting PEM fingerprint out of band.** Key downloads from the same hosting account do not independently establish trust.
6. Retrieve both immutable object **versions** to a separate read-only audit workstation and run:

```bash
python verify_provider_attestation.py \
  --observation observation.json \
  --attestation attestation.json \
  --pinned-public-key independently_pinned_p256.pem \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --kms-key-arn ARN_OF_ATTESTATION_KMS_KEY
```

Success means **a separately pinned key signed a statement bound to a Render deployment observation**, not that the actual scanner process generated a gamma snapshot or decision. Operational verification of CloudTrail, object lock, replay, cross-account key custody, and scanner process origin remains mandatory.

## Hard security limitations

- **NO scanner process attestation.** The collector observes deployment ID/Git SHA only. PID/boot ID/gamma execution/decision identities are deliberately excluded.
- **NO external ledger-head continuity.** This package is a separately stored, signed deployment-evidence *pilot*, not a Phase 4C full hash-chain checkpoint service. There is no cross-record monotonic sequencer, independent checkpoint consensus, or production evidence migration.
- **No production signing approval or independent runtime authentication.** AWS KMS P-256 public-key verification is a separate protocol from the Phase 4B Ed25519 research signer.
- **Provider consistency, not proof of execution:** independently requerying the same provider is valuable but is not a separately supervised scanner runtime.
- S3 Object Lock prohibits deletion/overwrite of protected **versions**, but AWS account administrators and compromised signing roles may still generate conflicting newly signed objects. Use cross-account custody, monitoring, audit logging, and additional external anchors.
- S3 notifications can be duplicated or delayed. Duplicate attestations are conditionally refused, rather than silently rewritten. Operational retry and dead-letter alarm procedures must be tested before long-running operation.
- No live AWS deployment was attempted, because no external AWS account access or separate authority was supplied. The APEX Render service was observed read-only through its management interface; it was not modified.

## Readiness verdict

`BUILD_READY`; `EXTERNAL_DEPLOYMENT_NOT_CONFIRMED`; `PRODUCTION_AUTHORIZATION=NO_GO`; `HISTORICAL_PROMOTION=BLOCKED_RESEARCH_ONLY`. All 3,569 historical gamma-linked decisions stay unmodified. **Do not enable `APEX_FORWARD_PROVENANCE_ENABLED`.**
