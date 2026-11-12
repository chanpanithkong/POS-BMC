# API endpoint catalogue

Base path `/api/v1`. Built from SRS 13.2 and the paths the Next.js frontend already calls. Permission codes follow SRS 4.2 (`module.resource.action`). "Phase" is when the endpoint is delivered; the status column is updated as phases complete.

Conventions for every endpoint (SRS 13.1):

- Authentication: `Authorization: Bearer <access token>` unless marked Public. Terminal requests also send `X-Terminal-Id`.
- `Idempotency-Key` header is required where marked **IK**.
- Draft edits accept `If-Match: <version>`.
- Errors use the standard envelope. 401 not signed in, 403 permission, limit or SoD, 404 missing or out of scope, 409 state or idempotency conflicts, 422 validation and business rules.
- Lists accept `limit`, `offset` or `cursor`, `sort`, `q` and the filters shown, and return `{items, total, next_cursor}`.

## Platform

| Method | Path | Purpose | Permission | Phase | Status |
|---|---|---|---|---|---|
| GET | /health | Liveness and database check | Public | 1 | Done, tested |

## Authentication and users (AUTH)

| Method | Path | Purpose | Permission | Phase | Status |
|---|---|---|---|---|---|
| POST | /auth/login | Username or email and password; sets refresh cookie | Public | 2 | Done, tested |
| POST | /auth/pin-login | PIN sign-in or switch on a registered terminal | Public, registered terminal | 2 | Done, tested |
| POST | /auth/refresh | Rotate refresh token; reuse revokes the family | Refresh cookie | 2 | Done, tested |
| POST | /auth/logout | Revoke session, clear cookie | Authenticated | 2 | Done, tested |
| GET | /auth/me | Current user, roles, permissions, limits, scope | Authenticated | 2 | Done, tested |
| PATCH | /auth/me | Name, phone, language | Authenticated | 2 | Done, tested |
| POST | /auth/change-password | Change own password | Authenticated | 2 | Done, tested |
| POST | /auth/forgot-password | Issue reset token (email delivery later) | Public | 2 | Done, tested |
| POST | /auth/reset-password | Use reset token | Public | 2 | Done, tested |
| GET | /auth/sessions | Own sessions, or all with users.user.manage | Authenticated | 2 | Done, tested |
| DELETE | /auth/sessions/{id} | Revoke a session | Owner or users.user.manage | 2 | Done, tested |
| POST | /auth/approvals/verify | Supervisor PIN; returns single-use approval token | Authenticated | 2 | Done, tested |
| GET | /users | List users | users.user.view | 2 | Done, tested |
| POST | /users | Create user | users.user.manage | 2 | Done, tested |
| GET | /users/{id} | User detail | users.user.view | 2 | Done, tested |
| PATCH | /users/{id} | Update profile, roles, scope (not own roles) | users.user.manage | 2 | Done, tested |
| DELETE | /users/{id} | Deactivate (soft delete; history kept) | users.user.manage | 2 | Done, tested |
| POST | /users/{id}/status | Activate or deactivate; revokes sessions | users.user.manage | 2 | Done, tested |
| POST | /users/{id}/unlock | Clear lockout | users.user.manage | 2 | Done, tested |
| POST | /users/{id}/pin | Set PIN (4 to 6 digits, unique per company, not sequential) | users.user.manage or self | 2 | Done, tested |
| GET POST PATCH DELETE | /roles, /roles/{id} | Roles and limits; system roles cannot be deleted | users.role.manage | 2 | Done, tested |
| GET | /permissions | Permission catalogue | users.role.view | 2 | Done, tested |
| GET POST PATCH DELETE | /employees, /employees/{id} | Employee profiles | users.user.manage | 2 | Done, tested |
| GET | /audit-logs | Audit trail with filters | audit.log.view | 2 | Done, tested |
| POST | /auth/pin, /approvals/verify | Aliases used by the frontend | Public / Authenticated | 2 | Done, tested |
| GET | /audit-logs/verify | Recompute the audit hash chain | audit.log.view | 2 | Done, tested |

## Organisation (ORG, BRN)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET PATCH | /companies/current | settings.settings.manage to change | 3 | Done, tested |
| GET PATCH | /settings | settings.settings.manage to change | 3 | Done, tested |
| GET POST PATCH | /branches, /branches/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /warehouses, /warehouses/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /locations, /locations/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /terminals, /terminals/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /tax-codes, /tax-codes/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /payment-methods, /payment-methods/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST | /currencies/rates | settings.settings.manage | 3 | Done, tested |
| GET PATCH | /document-sequences, /document-sequences/{id} | settings.settings.manage | 3 | Done, tested |
| GET POST PATCH | /receipt-templates, /receipt-templates/{id} | settings.settings.manage | 3 | Done, tested |

## Catalogue and pricing (PRD, CAT, PRC)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET | /products | products.product.view (cost fields need inventory.cost.view) | 3 | Done, tested |
| POST | /products | products.product.create | 3 | Done, tested |
| GET PATCH DELETE | /products/{id} | view, edit, delete (draft without movements only) | 3 | Done, tested |
| GET | /products/{id}/history | products.product.view | 3 | Done, tested |
| POST | /products/{id}/duplicate | products.product.create | 3 | Done, tested |
| GET | /products/barcode/{barcode} | pos.sale.create or products.product.view | 3 | Done, tested |
| GET | /products/barcodes | products.product.view | 3 | Done, tested |
| POST | /products/barcodes/generate | products.product.edit | 3 | Done, tested |
| GET POST PATCH DELETE | /categories, /brands, /units | products.category.manage | 3 | Done, tested |
| GET | /price-lists | pricing.price.view | 3 | Done, tested |
| GET POST DELETE | /prices, /prices/{id} | pricing.price.edit | 3 | Done, tested |
| GET | /prices/history | pricing.price.view | 3 | Done, tested |
| POST | /prices/bulk/preview, /prices/bulk | pricing.price.edit | 3 | Done, tested |
| GET | /products/{id}/price?unit_id&branch_id | products.product.view or pos.sale.create (resolved price and source) | 3 | Done, tested |
| GET | /files/products/{name} | Public, random file names (product images) | 3 | Done, tested |

## Inventory (INV, CST, ADJ, TRF, ALR)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET | /inventory/balances | inventory.stock.view | 4 | Done, tested |
| GET | /inventory/availability | inventory.stock.view or pos.sale.create | 4 | Done, tested |
| GET | /inventory/movements | inventory.stock.view | 4 | Done, tested |
| POST | /inventory/movements/{id}/reverse | inventory.movement.reverse **IK** | 4 | Done, tested |
| POST | /inventory/relocations | inventory.transfer.create **IK** | 4 | Done, tested |
| POST | /inventory/reconciliation | inventory.stock.view | 4 | Done, tested |
| POST | /inventory/opening-balances | inventory.adjustment.approve **IK** (products that never moved) | 4 | Done, tested |
| DELETE | /inventory/adjustments/{id} | inventory.adjustment.create (cancels; record kept) | 4 | Done, tested |
| GET | /inventory/batches | inventory.stock.view | 4 | Done, tested |
| GET | /inventory/reorder-suggestions | purchasing.order.view | 4 | Done, tested |
| GET POST PATCH | /inventory/adjustments, /{id} | inventory.adjustment.create | 4 | Done, tested |
| POST | /inventory/adjustments/{id}/submit, /approve, /reject, /post | create; approve; post **IK** | 4 | Done, tested |
| GET POST | /inventory/transfers | inventory.transfer.create | 4 | Done, tested |
| POST | /inventory/transfers/{id}/approve, /dispatch, /receive, /close, /cancel | approve; dispatch and receive **IK** | 4 | Done, tested |
| GET POST | /inventory/counts | inventory.count.create | 4 | Done, tested |
| PATCH | /inventory/counts/{id}/lines | inventory.count.create | 4 | Done, tested |
| POST | /inventory/counts/{id}/submit, /recount, /approve, /post, /cancel | count; approve; post **IK** | 4 | Done, tested |
| GET | /alerts | inventory.alert.view | 4 | Done, tested |
| POST | /alerts/{id}/action, /alerts/evaluate | inventory.alert.manage | 4 | Done, tested |

## POS, payments, cash, sales, documents, returns (POS, PAY, CSH, SAL, DOC, RET)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| POST | /sales | pos.sale.create **IK** | 5 | Done, tested |
| GET | /sales | sales.sale.view (own terminal without sales.sale.view_all) | 5 | Done, tested |
| GET | /sales/current, /sales/held | pos.sale.create | 5 | Done, tested |
| GET PATCH | /sales/{id} | view; PATCH line operations with If-Match | 5 | Done, tested |
| POST | /sales/{id}/hold, /resume | pos.sale.hold | 5 | Done, tested |
| POST | /sales/{id}/finalize | pos.sale.create **IK** | 5 | Done, tested |
| POST | /sales/{id}/cancel | pos.sale.cancel **IK** | 5 | Done, tested |
| POST | /sales/{id}/void | sales.sale.void, approver ≠ cashier **IK** | 5 | Done, tested |
| GET POST | /sales/{id}/payments | pos.sale.create **IK** | 5 | Done, tested |
| POST | /sales/{id}/payments/{pid}/resolve | pos.sale.create | 5 | Done, tested |
| GET | /payments | payments.payment.view | 5 | Done, tested |
| POST | /payments/{id}/refund | sales.refund.process **IK** | 5 | Done, tested |
| POST | /payments/{id}/reconcile | payments.payment.reconcile | 5 | Done, tested |
| GET | /sales/{id}/receipt | sales.sale.view | 5 | Done, tested |
| POST | /sales/{id}/reprint, /invoice | sales.sale.view | 5 | Done, tested |
| POST | /sales/{id}/returns/quote | sales.return.create | 5 | Done, tested |
| POST | /sales/{id}/returns | sales.return.create (+ approval) **IK** | 5 | Done, tested |
| GET | /returns, /refunds | sales.sale.view | 5 | Done, tested |
| POST | /returns/{id}/confirm-refund | sales.refund.process | 5 | Done, tested |
| POST | /refunds/{id}/confirm | sales.refund.process (pending refunds from voids) | 5 | Done, tested |
| GET | /cashier-sessions, /cashier-sessions/current | cash.session.view | 5 | Done, tested |
| POST | /cashier-sessions/open | cash.session.open **IK** | 5 | Done, tested |
| GET | /cashier-sessions/{id}/summary | cash.session.view (expected hidden until count) | 5 | Done, tested |
| POST | /cashier-sessions/{id}/movements | cash.session.open (+ approval above threshold) | 5 | Done, tested |
| POST | /cashier-sessions/{id}/close | cash.session.close **IK** | 5 | Done, tested |
| POST | /cashier-sessions/{id}/approve, /force-close | cash.session.approve | 5 | Done, tested |

## Purchasing and customers (PUR, GRN, CUS)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET POST PATCH DELETE | /suppliers, /suppliers/{id} | purchasing.supplier.manage | 6 |
| GET POST PATCH DELETE | /purchase-orders, /{id} | purchasing.order.create | 6 |
| POST | /purchase-orders/{id}/submit, /approve, /reject, /send, /cancel | approve needs purchasing.order.approve, creator excluded | 6 |
| GET POST DELETE | /goods-receipts, /{id} | purchasing.receipt.create | 6 |
| POST | /goods-receipts/{id}/post, /approve, /reject | post **IK** | 6 |
| GET POST | /supplier-invoices, /{id}/payments | purchasing.invoice.manage | 6 |
| GET POST | /purchase-returns, /{id}/approve, /dispatch, /credit | purchasing.return.manage | 6 |
| GET POST PATCH DELETE | /customers, /customers/{id} | customers.customer.manage | 6 |
| POST | /customers/{id}/anonymize | customers.personal_data.manage | 6 |
| GET POST PATCH DELETE | /customer-groups | customers.customer.manage | 6 |

## Reports and dashboard (RPT, DSH)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET | /dashboard | dashboard.dashboard.view | 7 |
| GET | /reports | Catalogue filtered by permission | 7 |
| GET | /reports/{id} | Per report, RPT-01 to RPT-34; `format=csv` or `xlsx` for files | 7 |
| GET | /reports/sales, /reports/inventory, /reports/gross-profit, /reports/cashier-sessions | SRS 13.2 grouped aliases | 7 |

## Advanced (NTF, IMP, EXP, PRM)

| Method | Path | Permission | Phase | Status |
|---|---|---|---|---|
| GET POST | /notifications, /notifications/read | Authenticated | 8 |
| GET | /imports/templates/{type} | imports.import.manage | 8 |
| POST | /imports/preview, /imports/commit **IK**, /imports/{id}/rollback | imports.import.manage | 8 |
| GET | /imports | imports.import.manage | 8 |
| POST | /exports/audit | Authenticated | 8 |
| GET POST PATCH DELETE | /expenses, /expense-categories | expenses.expense.create, approve | 8 |
| GET POST PATCH DELETE | /promotions, /coupons | promotions.promotion.manage | 8 (optional) |
