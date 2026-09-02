# Security policy

## Supported versions

Security fixes are applied to the latest `0.1.x` release while the project is pre-1.0.

## Reporting

Please use GitHub's private vulnerability reporting for this repository. Do not open a public issue
for a suspected vulnerability or include credentials, feature data, model artifacts, or exploit
details in public logs.

Include the affected version, deployment mode, reproduction, impact, and any proposed mitigation.

## Deployment warning

The built-in API key is a minimal guard for mutations, not enterprise IAM. Terminate TLS and enforce
identity, authorization, rate limiting and request limits at an ingress or service mesh. Configure an
audit HMAC key, encrypt storage, and keep model endpoint credentials in a secret manager.

Local `joblib` artifacts are deserialized in-process. Only load artifacts from a trusted admission
path after digest and provenance verification. A SHA-256 match against a writable manifest is not a
publisher signature.

See [docs/threat-model.md](docs/threat-model.md) for assets, trust boundaries, controls and residual
risks.

