# Security

EmailMonitor is currently a documentation/design baseline, not a deployed or security-certified product. See [threat model](docs/11-security-and-threat-model.md) and [source/privacy controls](docs/12-source-governance-and-privacy.md).

## Reporting

Do not post credentials, actual contact lists, customer data, exploitable production details or confidential documents in a public issue. Use GitHub private vulnerability reporting if the repository owner has enabled it; otherwise contact the owner through an established private channel. No security email address or reporting SLA has been configured by this documentation pack.

For an active deployment, follow the customer/platform incident-response channel agreed in its contract. Revoke exposed secrets promptly, preserve minimal forensic evidence securely and coordinate remediation with the responsible owner. A public repository change does not remediate a leaked credential.

## Development safety

No real-world crawling, production credentials, email sending or external AI calls in default tests. Untrusted URLs/content are data. Production must reject test auth/fixture-network overrides and enforce tenant, network, document and export controls.

Supported release/security-patch windows are to be defined before the first production release. Do not claim a SOC 2, ISO, GDPR or other compliance certification from these specifications alone.
