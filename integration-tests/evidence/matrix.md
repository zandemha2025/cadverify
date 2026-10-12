# Integration evidence coverage

Percentages count demonstrated stages in each customer workflow, not uptime, pass probability or vendor certification.
All six stages remain in the denominator. Missing evidence means NOT_DEMONSTRATED, not failed.

| Workflow | Scope | Real system stages | Coverage | Evidence class | Vendor attempts | Supplied mock/fixture runs |
|---|---|---:|---:|---|---|---:|
| SAP S/4HANA product and BOM preview | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| PTC Windchill part/BOM import | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Okta SAML sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Microsoft Entra SAML sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| PingFederate SAML sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Okta OIDC sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Microsoft Entra OIDC sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| PingFederate OIDC sign-in | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Okta SCIM provisioning lifecycle | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Microsoft Entra SCIM provisioning lifecycle | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Resend magic-link email delivery and use | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Resend invitation email delivery and acceptance | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Resend pilot-intake alert delivery | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Batch webhook delivery and retries | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Cloudflare Turnstile magic-link challenge | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Cloudflare Turnstile pilot-intake challenge | customer_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Replicate TripoSR reconstruction | optional_disabled | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Google OAuth sign-in | implemented_not_advertised | 0/6 | 0.00% | none supplied | unknown (0 known; 0 unknown runs) | 0 |
| Local Keycloak basic OIDC sign-in (HTTP loopback) | local_test_target | 4/6 | 66.67% | self_hosted_oss_test | 0 | 0 |

## Stage evidence

| Workflow | Configuration/trust | Authentication/transport | Functional action | Reconciliation | Failure handling | Recovery/retry |
|---|---|---|---|---|---|---|
| SAP S/4HANA product and BOM preview | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| PTC Windchill part/BOM import | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Okta SAML sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Microsoft Entra SAML sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| PingFederate SAML sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Okta OIDC sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Microsoft Entra OIDC sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| PingFederate OIDC sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Okta SCIM provisioning lifecycle | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Microsoft Entra SCIM provisioning lifecycle | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Resend magic-link email delivery and use | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Resend invitation email delivery and acceptance | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Resend pilot-intake alert delivery | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Batch webhook delivery and retries | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Cloudflare Turnstile magic-link challenge | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Cloudflare Turnstile pilot-intake challenge | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Replicate TripoSR reconstruction | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Google OAuth sign-in | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED | NOT_DEMONSTRATED |
| Local Keycloak basic OIDC sign-in (HTTP loopback) | PASS | PASS | PASS | PASS | NOT_DEMONSTRATED | NOT_DEMONSTRATED |

## Separate file workflows

| Workflow | External connection coverage | Real-source reconciliation |
|---|---|---|
| SAP manifest CSV | N/A | NOT_DEMONSTRATED |
| PLM manifest CSV | N/A | NOT_DEMONSTRATED |
| Quote/actuals CSV (supplier quotes / ERP actuals) | N/A | NOT_DEMONSTRATED |
| CAD file interchange (separate capability) | N/A | NOT_DEMONSTRATED |

A self-hosted Keycloak result applies only to the local Keycloak target. It cannot establish Okta, Entra or PingFederate readiness.
Mock, fixture and simulator runs receive zero real-system credit. Raw receipts and tenant authorization still require human review.
