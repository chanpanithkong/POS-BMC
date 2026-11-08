# Requirements mapping

Source: PIMS-SRS-001 v1.0, draft for review, 27 October 2026. This maps every functional requirement to the screens that serve it, and records assumptions and gaps.

## Summary

293 functional requirements mapped across 26 modules.

| Status | Count | Meaning |
|---|---|---|
| Implemented | 251 | Works in this frontend against the mock server |
| Simulated | 9 | The workflow works, but the real effect needs the backend, a provider or hardware |
| Partial | 16 | Part of the requirement works; the note says what is missing |
| Deferred | 17 | Not built. Mostly Should or Could items, SRS phase 7, or backend jobs |

"Implemented" means behaviour in the browser. No SRS performance target, security control, or hardware test has been verified, and all SRS test statuses remain "Not run".

## Role access

Default permissions follow SRS 4.3 and 14.2 in `src/constants/roles.ts`. Sidebar items, screens and server responses all use them. Final values need approval (D-12).

## Decisions applied

The SRS leaves these open. The recommended default was used, and each one is a setting or a single place to change.

| Item | Applied default | Where |
|---|---|---|
| D-01 Offline POS | Online only | No offline mode built |
| D-04 Payment methods | Cash USD/KHR; card, QR, bank transfer by reference | /settings, Payment methods |
| D-05 Costing | Weighted average, company scope | Mock server |
| D-06 Negative stock | Not allowed | /settings, General |
| D-07 Reservations | None | Not built |
| D-11 Credit sales | Not enabled | Not built |
| D-13 Separation of duties | Strict, reduced mode available | /settings, General |

## Assumptions and conflicts

- **SRS over brief.** The brief placed the POS inside the dashboard group. SRS 14.1 requires it full-screen without the sidebar, so it lives in `src/app/(pos)`.
- **Extra modules.** SRS 14.2 adds Promotions and Cashier Sessions to the brief's sidebar, so both are included. Customer groups, employees, alerts and the import wizard also come from the SRS.
- **TanStack Query** was added because SRS 12.2 specifies it and the brief asked for data-fetching hooks.
- **Tax.** The 10% TAX-STD rate is an illustrative placeholder. Rates, inclusive pricing and receipt content need confirmation (V-01, V-02).
- **Sample data** (business, products, prices, people) is invented for demonstration.
- **Decimals.** The mock server rounds JavaScript numbers. FastAPI must use Decimal (NFR-INT-010). `src/lib/api/casing.ts` converts decimal strings at the HTTP boundary.
- **Table paging** is client-side. At SRS workload W1 (50,000 products) the product, stock and movement lists need server-side paging.

## Non-functional status

| Area | Status |
|---|---|
| Localization (NFR-LOC-002) | Partial. English and Khmer switch covers navigation and POS labels only, and the Khmer needs review by a Khmer reader. Forms and messages are English. |
| Formatting (NFR-LOC-003, 004) | USD, KHR, DD/MM/YYYY, 24-hour, Asia/Phnom_Penh are applied |
| POS keyboard and scanner (NFR-USA-002, 003) | F2, F3, F4, F6, F7, F8, F9, F12, Del, arrows; wedge scanner input without focus |
| Touch targets (NFR-USA-004) | Main POS actions are 48 px or taller; Pay is 64 px |
| Responsive (NFR-USA-006) | See the QA notes in the README |
| Accessibility (NFR-USA-008) | Labels and error association are built in; no axe audit has been run |
| Performance, security, reliability, backup, hardware | Require the backend and test environment; not verified |

## Workflows

| Workflow | Screens |
|---|---|
| WF-01 Product creation | /products/new |
| WF-02 Price update | /products/pricing |
| WF-03, 04, 05, 06, 07 Checkout, cash, split, failed payment, receipt | /pos |
| WF-08, 09 Refund, exchange | /sales/returns |
| WF-10 Purchase order | /purchases |
| WF-11 Goods receiving | /purchases/receiving |
| WF-12 Supplier return | /purchases/returns |
| WF-13 Stock transfer | /inventory/transfers |
| WF-14 Stocktaking | /inventory/stocktakes |
| WF-15 Adjustment approval | /inventory/adjustments |
| WF-16 Low-stock replenishment | /inventory/alerts, /purchases |
| WF-17 Session open and close | /pos, /cashier-sessions |
| WF-18 Branch inventory reporting | /reports |
| WF-19 Product import | /settings/import |
| WF-20 End-of-day reconciliation | /cashier-sessions, /sales/payments, /reports/RPT-01. There is no "close day" lock. |

## Functional requirements

### AUTH

Primary screens: /login, /users, /users/roles, /users/employees, /users/activity, /profile

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-AUTH-001 | Login and logout | Must | Simulated | Sign-in works; tokens are mock values. HttpOnly refresh cookies come from FastAPI. |
| FR-AUTH-002 | Terminal PIN login | Must | Implemented |  |
| FR-AUTH-003 | User creation and modification | Must | Implemented |  |
| FR-AUTH-004 | Password management and reset | Must | Simulated | Policy checks exist; Argon2id and reset emails need the backend. |
| FR-AUTH-005 | Activation and deactivation | Must | Implemented |  |
| FR-AUTH-006 | Role and permission management | Must | Implemented |  |
| FR-AUTH-007 | Session management | Must | Partial | Sessions listed and revoked, POS idle lock works; 30 min and 12 h expiry need the backend. |
| FR-AUTH-008 | Failed-login protection | Must | Simulated | Lockout after 5 failures works; IP rate limiting needs the backend. |
| FR-AUTH-009 | Server-side authorisation | Must | Simulated | Enforced in the mock server. Must be re-implemented in FastAPI. |
| FR-AUTH-010 | Optional MFA | Should | Deferred | TOTP MFA needs the backend. |
| FR-AUTH-011 | User activity logs | Must | Implemented |  |
| FR-AUTH-012 | Branch access restrictions | Must | Implemented |  |
| FR-AUTH-013 | Employee profiles | Should | Implemented |  |

### ORG

Primary screens: /settings

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-ORG-001 | Company profile | Must | Implemented |  |
| FR-ORG-002 | Branch management | Must | Implemented |  |
| FR-ORG-003 | Warehouse management | Must | Implemented |  |
| FR-ORG-004 | Stock locations | Must | Implemented |  |
| FR-ORG-005 | POS terminal registration | Must | Implemented |  |
| FR-ORG-006 | Cashier-terminal assignment | Should | Implemented |  |
| FR-ORG-007 | Business hours and business date | Should | Implemented |  |
| FR-ORG-008 | Fiscal year and reporting periods | Should | Implemented |  |
| FR-ORG-009 | Currency settings | Must | Implemented |  |
| FR-ORG-010 | Receipt numbering | Must | Implemented |  |
| FR-ORG-011 | Product numbering | Should | Implemented |  |
| FR-ORG-012 | Branch-specific pricing switch | Should | Implemented |  |

### PRD

Primary screens: /products, /products/new, /products/[id], /products/barcodes

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-PRD-001 | Product creation | Must | Implemented |  |
| FR-PRD-002 | SKU and product code | Must | Implemented |  |
| FR-PRD-003 | Barcodes | Must | Implemented |  |
| FR-PRD-004 | Units on product | Must | Implemented |  |
| FR-PRD-005 | Prices on product | Must | Implemented |  |
| FR-PRD-006 | Purchase cost reference | Must | Implemented |  |
| FR-PRD-007 | Tax configuration | Must | Implemented |  |
| FR-PRD-008 | Supplier association | Should | Implemented |  |
| FR-PRD-009 | Stock parameters | Must | Implemented |  |
| FR-PRD-010 | Product status | Must | Implemented |  |
| FR-PRD-011 | Variants | Must | Implemented |  |
| FR-PRD-012 | Weight and volume products | Must | Implemented |  |
| FR-PRD-013 | Non-stock services | Must | Implemented |  |
| FR-PRD-014 | Expiry and batch tracking | Should | Implemented |  |
| FR-PRD-015 | Serial-number tracking | Could | Deferred | Serial tracking is SRS phase 7. |
| FR-PRD-016 | Bundles and kits | Could | Deferred | Bundles are SRS phase 7. |
| FR-PRD-017 | Product search and filters | Must | Implemented |  |
| FR-PRD-018 | Change history | Must | Implemented |  |

### CAT

Primary screens: /products/categories, /products/brands, /products/units

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-CAT-001 | Category management | Must | Implemented |  |
| FR-CAT-002 | Category settings | Should | Implemented |  |
| FR-CAT-003 | Brand management | Must | Implemented |  |
| FR-CAT-004 | Unit-of-measure management | Must | Implemented |  |
| FR-CAT-005 | Unit conversions | Must | Implemented |  |
| FR-CAT-006 | Base-quantity calculation | Must | Implemented |  |
| FR-CAT-007 | Category-level reporting | Must | Implemented |  |
| FR-CAT-008 | Product filtering | Must | Implemented |  |

### POS

Primary screens: /pos

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-POS-001 | Barcode scanning | Must | Implemented |  |
| FR-POS-002 | Product search | Must | Implemented |  |
| FR-POS-003 | Category browsing | Must | Implemented |  |
| FR-POS-004 | Quantity entry and adjustment | Must | Implemented |  |
| FR-POS-005 | Unit price display | Must | Implemented |  |
| FR-POS-006 | Line and order discounts | Must | Implemented |  |
| FR-POS-007 | Tax and totals | Must | Implemented |  |
| FR-POS-008 | Customer selection | Must | Implemented |  |
| FR-POS-009 | Hold and resume sale | Must | Implemented |  |
| FR-POS-010 | Cancel sale | Must | Implemented |  |
| FR-POS-011 | Availability and out-of-stock warnings | Must | Implemented |  |
| FR-POS-012 | Price overrides | Must | Implemented |  |
| FR-POS-013 | Refund and return initiation | Must | Implemented |  |
| FR-POS-014 | Cashier and terminal identification | Must | Implemented |  |
| FR-POS-015 | Sales history on POS | Must | Implemented |  |
| FR-POS-016 | Keyboard shortcuts | Should | Implemented |  |
| FR-POS-017 | Idempotent sale operations | Must | Implemented |  |

### PAY

Primary screens: /pos (payment dialog), /sales/payments

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-PAY-001 | Cash payments | Must | Implemented |  |
| FR-PAY-002 | Card payments | Must | Simulated | Standalone terminal by reference (A-06). |
| FR-PAY-003 | QR and electronic payments | Should | Simulated | QR by verified reference (A-06, V-03). No dynamic QR yet. |
| FR-PAY-004 | Bank transfers | Should | Implemented |  |
| FR-PAY-005 | Split payments | Must | Implemented |  |
| FR-PAY-006 | Partial payments | Could | Deferred | Partial payment is off by default (BR-PAY-007, D-11). |
| FR-PAY-007 | Change calculation | Must | Implemented |  |
| FR-PAY-008 | Payment statuses | Must | Implemented |  |
| FR-PAY-009 | Provider confirmation | Must | Simulated | Cashier-entered verified reference; provider callbacks need integration. |
| FR-PAY-010 | Duplicate prevention | Must | Implemented |  |
| FR-PAY-011 | Payment failure handling | Must | Implemented |  |
| FR-PAY-012 | Payment cancellation | Must | Implemented |  |
| FR-PAY-013 | Payment references | Must | Implemented |  |
| FR-PAY-014 | Payment reconciliation | Should | Partial | Manual match per payment; settlement file import pending provider details. |
| FR-PAY-015 | Pending payment recovery | Must | Deferred | Background recovery job belongs to the backend worker. |

### CSH

Primary screens: /pos (open session), /cashier-sessions

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-CSH-001 | Open session | Must | Implemented |  |
| FR-CSH-002 | Cash sales and refunds | Must | Implemented |  |
| FR-CSH-003 | Cash in and cash out | Must | Implemented |  |
| FR-CSH-004 | Paid-out expenses | Should | Implemented |  |
| FR-CSH-005 | Cash drops | Should | Implemented |  |
| FR-CSH-006 | Expected cash calculation | Must | Implemented |  |
| FR-CSH-007 | Blind closing count | Must | Implemented |  |
| FR-CSH-008 | Overage and shortage | Must | Implemented |  |
| FR-CSH-009 | Session closing and manager review | Must | Implemented |  |
| FR-CSH-010 | Non-cash totals | Must | Implemented |  |
| FR-CSH-011 | Session history | Must | Implemented |  |
| FR-CSH-012 | Session permissions | Must | Implemented |  |

### SAL

Primary screens: /sales, /sales/held

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-SAL-001 | Sales transactions | Must | Implemented |  |
| FR-SAL-002 | Sale lines | Must | Implemented |  |
| FR-SAL-003 | Sale status | Must | Implemented |  |
| FR-SAL-004 | Payment status | Must | Implemented |  |
| FR-SAL-005 | Fulfilment status | Could | Deferred | Status stored on sales; no fulfilment screen (Could). |
| FR-SAL-006 | Discounts and tax on sales | Must | Implemented |  |
| FR-SAL-007 | Associations | Must | Implemented |  |
| FR-SAL-008 | Cancellation | Must | Implemented |  |
| FR-SAL-009 | Void | Must | Implemented |  |
| FR-SAL-010 | Returns and exchanges link | Must | Implemented |  |
| FR-SAL-011 | Transaction history | Must | Implemented |  |
| FR-SAL-012 | No deletion of finalized sales | Must | Implemented |  |

### DOC

Primary screens: /pos (receipt), /sales (reprint, invoice), /settings (Receipts, Numbering)

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-DOC-001 | Receipt generation | Must | Implemented |  |
| FR-DOC-002 | Invoice generation | Should | Partial | A4 invoice via browser print; mandatory content pending V-02. |
| FR-DOC-003 | Templates | Must | Implemented |  |
| FR-DOC-004 | Sequential numbering | Must | Implemented |  |
| FR-DOC-005 | Thermal printing | Must | Simulated | Browser print preview; ESC/POS needs the local print agent. |
| FR-DOC-006 | PDF output | Must | Partial | PDF through the browser print dialog; server PDF with embedded Khmer fonts is pending. |
| FR-DOC-007 | Reprinting | Must | Implemented |  |
| FR-DOC-008 | Refund references | Must | Implemented |  |
| FR-DOC-009 | Email delivery | Could | Deferred | Email needs the backend. |
| FR-DOC-010 | Document snapshot | Must | Implemented |  |

### INV

Primary screens: /inventory, /inventory/movements, /inventory/expiring

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-INV-001 | Current stock by product | Must | Implemented |  |
| FR-INV-002 | Stock by branch, warehouse and location | Must | Implemented |  |
| FR-INV-003 | Movement ledger | Must | Implemented |  |
| FR-INV-004 | Atomic balance updates | Must | Simulated | Mock server applies balance and movement in one rollback unit; DB transactions need PostgreSQL. |
| FR-INV-005 | Stock receipts and issues | Must | Implemented |  |
| FR-INV-006 | Relocation within a warehouse | Should | Implemented |  |
| FR-INV-007 | Reservations | Should | Deferred | Reservations (Should). The reserved column exists and is always zero. |
| FR-INV-008 | Availability service | Must | Implemented |  |
| FR-INV-009 | Negative stock prevention | Must | Implemented |  |
| FR-INV-010 | Damaged, expired and lost stock | Must | Implemented |  |
| FR-INV-011 | Write-offs | Must | Implemented |  |
| FR-INV-012 | Movement history | Must | Implemented |  |
| FR-INV-013 | Corrections by reversal | Must | Implemented |  |
| FR-INV-014 | Batch and expiry | Should | Implemented |  |
| FR-INV-015 | Serial numbers | Could | Deferred | Serial tracking is SRS phase 7. |
| FR-INV-016 | Balance reconciliation | Must | Partial | On-demand reconciliation works; nightly job belongs to the backend. |
| FR-INV-017 | Discrepancy reporting | Must | Implemented |  |

### CST

Primary screens: /products/[id] (Prices), /reports/RPT-13, /reports/RPT-15

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-CST-001 | Configurable costing method | Must | Partial | Weighted average, company scope (D-05). FIFO not built. |
| FR-CST-002 | Purchase cost capture | Must | Implemented |  |
| FR-CST-003 | Landed costs | Could | Deferred | Landed costs (Could). |
| FR-CST-004 | COGS at sale | Must | Implemented |  |
| FR-CST-005 | Cost adjustment | Should | Deferred | Value-only cost adjustment (Should). |
| FR-CST-006 | Returned goods valuation | Must | Implemented |  |
| FR-CST-007 | Damaged goods write-off | Must | Implemented |  |
| FR-CST-008 | Inventory valuation report | Must | Implemented |  |
| FR-CST-009 | Gross profit calculation | Must | Implemented |  |
| FR-CST-010 | Historical cost preservation | Must | Implemented |  |
| FR-CST-011 | Accounting entries | Could | Deferred | Accounting journals (Could, D-16). |

### PUR

Primary screens: /purchases, /purchases/invoices, /purchases/returns, /suppliers, /suppliers/[id]

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-PUR-001 | Supplier records | Must | Implemented |  |
| FR-PUR-002 | Supplier contacts | Should | Implemented |  |
| FR-PUR-003 | Purchase requisitions | Could | Deferred | Requisitions (Could). |
| FR-PUR-004 | Purchase orders | Must | Implemented |  |
| FR-PUR-005 | PO approval | Must | Implemented |  |
| FR-PUR-006 | PO sending | Should | Partial | Print or PDF works; supplier email needs the backend. |
| FR-PUR-007 | Supplier invoices and matching | Should | Implemented |  |
| FR-PUR-008 | Purchase returns | Should | Implemented |  |
| FR-PUR-009 | Supplier credit notes | Should | Implemented |  |
| FR-PUR-010 | Supplier payments or references | Could | Implemented |  |
| FR-PUR-011 | Supplier balances | Could | Implemented |  |
| FR-PUR-012 | Supplier pricing and lead times | Should | Partial | Cost and lead time per supplier; no effective dating. |
| FR-PUR-013 | Purchase history and performance | Should | Implemented |  |
| FR-PUR-014 | PO cancellation and short-close | Must | Implemented |  |

### GRN

Primary screens: /purchases/receiving

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-GRN-001 | Receive against PO | Must | Implemented |  |
| FR-GRN-002 | Receive without PO | Should | Implemented |  |
| FR-GRN-003 | Partial receipt | Must | Implemented |  |
| FR-GRN-004 | Barcode-assisted receiving | Must | Implemented |  |
| FR-GRN-005 | Batch, expiry and serial capture | Should | Partial | Batch and expiry captured; serials are phase 7. |
| FR-GRN-006 | Quantity verification | Must | Implemented |  |
| FR-GRN-007 | Damaged goods recording | Must | Implemented |  |
| FR-GRN-008 | Discrepancies and approval | Must | Implemented |  |
| FR-GRN-009 | Supplier delivery references | Must | Partial | Delivery note and invoice number stored; file attachments pending. |
| FR-GRN-010 | Single posting | Must | Implemented |  |

### TRF

Primary screens: /inventory/transfers

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-TRF-001 | Transfer requests | Must | Implemented |  |
| FR-TRF-002 | Transfer approval | Must | Implemented |  |
| FR-TRF-003 | Dispatch | Must | Implemented |  |
| FR-TRF-004 | In-transit stock | Must | Implemented |  |
| FR-TRF-005 | Receipt confirmation | Must | Implemented |  |
| FR-TRF-006 | Partial receipt | Should | Implemented |  |
| FR-TRF-007 | Discrepancies | Must | Implemented |  |
| FR-TRF-008 | Cancellation | Must | Implemented |  |
| FR-TRF-009 | Transfer history | Must | Implemented |  |

### ADJ

Primary screens: /inventory/adjustments, /inventory/stocktakes

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-ADJ-001 | Adjustment requests | Must | Partial | Lines, reasons and notes; file attachments pending. |
| FR-ADJ-002 | Adjustment approval | Must | Implemented |  |
| FR-ADJ-003 | Adjustment posting | Must | Implemented |  |
| FR-ADJ-004 | Cycle counting | Should | Implemented |  |
| FR-ADJ-005 | Full stocktake | Must | Implemented |  |
| FR-ADJ-006 | Count entry | Must | Implemented |  |
| FR-ADJ-007 | Variance calculation | Must | Implemented |  |
| FR-ADJ-008 | Investigation | Should | Implemented |  |
| FR-ADJ-009 | Delta posting | Must | Implemented |  |
| FR-ADJ-010 | Adjustment history | Must | Implemented |  |

### RET

Primary screens: /sales/returns

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-RET-001 | Customer returns | Must | Implemented |  |
| FR-RET-002 | Full and partial returns | Must | Implemented |  |
| FR-RET-003 | Refunds | Must | Implemented |  |
| FR-RET-004 | Exchanges | Must | Implemented |  |
| FR-RET-005 | Store credit | Could | Implemented |  |
| FR-RET-006 | Return reasons and condition | Must | Implemented |  |
| FR-RET-007 | Restocking decision | Must | Implemented |  |
| FR-RET-008 | Refund approval | Must | Implemented |  |
| FR-RET-009 | Payment refund reference | Must | Implemented |  |
| FR-RET-010 | Eligibility rules | Must | Implemented |  |
| FR-RET-011 | Return receipts | Must | Implemented |  |

### CUS

Primary screens: /customers, /customers/[id], /customers/groups

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-CUS-001 | Customer profiles | Must | Implemented |  |
| FR-CUS-002 | Customer search | Must | Implemented |  |
| FR-CUS-003 | Walk-in customers | Must | Implemented |  |
| FR-CUS-004 | Purchase history | Should | Implemented |  |
| FR-CUS-005 | Customer groups and pricing groups | Should | Implemented |  |
| FR-CUS-006 | Customer discounts | Should | Implemented |  |
| FR-CUS-007 | Store credit | Could | Implemented |  |
| FR-CUS-008 | Credit sales and statements | Could | Deferred | Credit sales are out of MVP (D-11). |
| FR-CUS-009 | Personal data controls | Must | Implemented |  |

### PRM

Primary screens: /promotions

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-PRM-001 | Loyalty points | Could | Implemented |  |
| FR-PRM-002 | Membership levels | Could | Partial | Fixed Member, Silver, Gold tiers; tier setup screen not built. |
| FR-PRM-003 | Promotion rules | Could | Implemented |  |
| FR-PRM-004 | Coupon codes | Could | Implemented |  |
| FR-PRM-005 | Loyalty redemption | Could | Deferred | Redeeming points as tender is not built. |
| FR-PRM-006 | Validity and limits | Could | Implemented |  |
| FR-PRM-007 | Precedence and combination | Could | Partial | Applied promotion shown on the line; non-applied promotions are not explained. |
| FR-PRM-008 | Return effect | Could | Implemented |  |
| FR-PRM-009 | Override recording | Could | Implemented |  |

### PRC

Primary screens: /products/pricing

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-PRC-001 | Standard and retail price | Must | Implemented |  |
| FR-PRC-002 | Wholesale price | Should | Implemented |  |
| FR-PRC-003 | Branch-specific price | Should | Implemented |  |
| FR-PRC-004 | Customer-group price | Should | Implemented |  |
| FR-PRC-005 | Promotion price | Could | Implemented |  |
| FR-PRC-006 | Effective dates | Must | Implemented |  |
| FR-PRC-007 | Price change history | Must | Implemented |  |
| FR-PRC-008 | Bulk price updates | Should | Implemented |  |
| FR-PRC-009 | Price import | Should | Implemented |  |
| FR-PRC-010 | Minimum margin warnings | Should | Implemented |  |
| FR-PRC-011 | Price override permissions | Must | Implemented |  |
| FR-PRC-012 | Price resolution service | Must | Implemented |  |

### ALR

Primary screens: /inventory/alerts

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-ALR-001 | Low-stock alerts | Must | Implemented |  |
| FR-ALR-002 | Out-of-stock alerts | Must | Implemented |  |
| FR-ALR-003 | Overstock alerts | Should | Implemented |  |
| FR-ALR-004 | Expiration warnings | Should | Implemented |  |
| FR-ALR-005 | Reorder suggestions | Should | Implemented |  |
| FR-ALR-006 | Slow-moving alerts | Should | Implemented |  |
| FR-ALR-007 | Negative stock alerts | Must | Implemented |  |
| FR-ALR-008 | Unusual adjustment alerts | Should | Implemented |  |
| FR-ALR-009 | Configurable thresholds | Must | Implemented |  |
| FR-ALR-010 | Assignment and lifecycle | Should | Implemented |  |

### EXP

Primary screens: /expenses, /expenses/categories

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-EXP-001 | Expense categories | Could | Implemented |  |
| FR-EXP-002 | Expense recording | Could | Implemented |  |
| FR-EXP-003 | Expense approval | Could | Implemented |  |
| FR-EXP-004 | Drawer paid-outs | Could | Implemented |  |
| FR-EXP-005 | Expense reporting | Could | Implemented |  |
| FR-EXP-006 | Separation from COGS | Could | Implemented |  |

### DSH

Primary screens: /dashboard

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-DSH-001 | Owner dashboard | Should | Implemented |  |
| FR-DSH-002 | Manager dashboard | Should | Implemented |  |
| FR-DSH-003 | Inventory dashboard | Should | Implemented |  |
| FR-DSH-004 | Cashier dashboard | Should | Implemented |  |
| FR-DSH-005 | KPI definitions | Should | Implemented |  |
| FR-DSH-006 | Permissions and scope | Must | Implemented |  |
| FR-DSH-007 | Reconciliation with reports | Must | Implemented |  |
| FR-DSH-008 | Drill-down | Should | Implemented |  |

### RPT

Primary screens: /reports, /reports/[id]

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-RPT-001 | Sales reports | Must | Implemented |  |
| FR-RPT-002 | Discount, refund and void reports | Must | Implemented |  |
| FR-RPT-003 | Tax summary | Should | Implemented |  |
| FR-RPT-004 | Gross profit and margin | Must | Implemented |  |
| FR-RPT-005 | Inventory reports | Must | Implemented |  |
| FR-RPT-006 | Purchasing reports | Should | Implemented |  |
| FR-RPT-007 | Cashier and payment reports | Must | Implemented |  |
| FR-RPT-008 | Business performance | Should | Implemented |  |
| FR-RPT-009 | Control exceptions | Should | Implemented |  |
| FR-RPT-010 | Filters | Must | Implemented |  |
| FR-RPT-011 | Exports and printing | Must | Partial | Excel and CSV are real files; PDF uses the browser print dialog. |
| FR-RPT-012 | Reconciliation checks | Should | Implemented |  |

### BRN

Primary screens: Header branch selector, /settings, /reports

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-BRN-001 | Centralized catalogue | Must | Partial | One shared catalogue. POS honours branch activation flags; no screen edits them yet. |
| FR-BRN-002 | Branch-specific stock | Must | Implemented |  |
| FR-BRN-003 | Branch-specific pricing | Should | Implemented |  |
| FR-BRN-004 | Branch-specific terminals | Must | Implemented |  |
| FR-BRN-005 | Inter-branch transfers | Must | Implemented |  |
| FR-BRN-006 | Branch-level users and permissions | Must | Implemented |  |
| FR-BRN-007 | Branch-level reports | Must | Implemented |  |
| FR-BRN-008 | Consolidated reporting | Should | Implemented |  |
| FR-BRN-009 | Shared suppliers and customers | Should | Implemented |  |

### NTF

Primary screens: Header bell, /notifications

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-NTF-001 | Low-stock and expiration notifications | Should | Implemented |  |
| FR-NTF-002 | Purchase approval notifications | Should | Implemented |  |
| FR-NTF-003 | Receipt discrepancy notifications | Should | Implemented |  |
| FR-NTF-004 | Pending transfer notifications | Should | Implemented |  |
| FR-NTF-005 | Refund approval notifications | Must | Implemented |  |
| FR-NTF-006 | Cashier closing reminders | Should | Deferred | Session reminders need a scheduled job. |
| FR-NTF-007 | System error notifications | Must | Deferred | System error notifications need the backend. |
| FR-NTF-008 | In-app and email channels | Should | Partial | In-app only; email and preferences need the backend. |

### IMP

Primary screens: /settings/import, table export menus

| ID | Requirement | Priority | Status | Note |
|---|---|---|---|---|
| FR-IMP-001 | Product import | Must | Implemented |  |
| FR-IMP-002 | Barcode import | Must | Implemented |  |
| FR-IMP-003 | Supplier and customer import | Should | Implemented |  |
| FR-IMP-004 | Opening inventory import | Must | Implemented |  |
| FR-IMP-005 | Price import | Should | Implemented |  |
| FR-IMP-006 | Stock count import | Should | Implemented |  |
| FR-IMP-007 | Preview and error report | Must | Implemented |  |
| FR-IMP-008 | Import history | Must | Implemented |  |
| FR-IMP-009 | Permission checks | Must | Implemented |  |
| FR-IMP-010 | Rollback and correction | Should | Implemented |  |
| FR-IMP-011 | Exports | Must | Implemented |  |
