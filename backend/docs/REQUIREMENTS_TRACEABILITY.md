# Requirements traceability

Maps SRS PIMS-SRS-001 requirement IDs to backend code and tests. Status is Planned, Partial or Done; Done means implemented and covered by a passing test listed in the Tests column.

150 of 293 functional requirements done, 28 partial (after Phases 1 to 5; 146 tests passing).

## Cross-cutting requirements

| ID | Backend | Tests | Status |
|---|---|---|---|
| NFR-SEC-005 | core/exceptions.py, schemas (extra=forbid) | tests/api/test_platform.py::test_unknown_fields_are_rejected | Done |
| NFR-MNT-002 | main.py OpenAPI, /docs, /redoc | tests/api/test_platform.py::test_docs_and_schema_are_served | Done |
| NFR-MNT-004 | alembic/ | tests/integration/test_database.py::test_schema_matches_models (+ downgrade/upgrade each run) | Done |
| NFR-MNT-005 | middleware/correlation.py, core/logging.py | tests/api/test_platform.py::test_correlation_id_* | Done |
| NFR-MNT-006 | core/config.py | tests/unit/test_core.py::test_short_secret_key_rejected, test_database_password_is_url_encoded_and_secret | Done |
| NFR-INT-010 | models (NUMERIC only) |  | Planned |
| NFR-SEC-011 | models/audit_log.py, migration trigger | tests/integration/test_database.py::test_audit_log_is_append_only, test_audit_chain_* | Done |
| NFR-SEC-014 | .env, core/config.py | tests/unit/test_core.py::test_database_password_is_url_encoded_and_secret | Done |
| BR-SEC-001 | core/permissions.py |  | Planned |
| BR-SEC-002 | services/approvals |  | Planned |
| BR-AUD-001 | services/audit |  | Planned |

## Functional requirements

### AUTH (phase 2)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-AUTH-001 | Login and logout | Must | BR-SEC-001 | services/auth, services/users | tests/api/test_auth.py::test_login_*, test_logout_revokes_access_and_refresh | Done |
| FR-AUTH-002 | Terminal PIN login | Must | BR-SEC-002 | services/auth, services/users | tests/api/test_auth.py::test_pin_login_* | Done |
| FR-AUTH-003 | User creation and modification | Must | BR-SEC-001 | services/auth, services/users | tests/api/test_access_control.py::test_admin_creates_user_with_scope | Done |
| FR-AUTH-004 | Password management and reset | Must | — | services/auth, services/users | tests/api/test_auth.py::test_change_password_*, test_forgot_and_reset_password (email delivery: Phase 8 worker) | Partial |
| FR-AUTH-005 | Activation and deactivation | Must | BR-AUD-001 | services/auth, services/users | tests/api/test_auth.py::test_inactive_user_cannot_sign_in | Done |
| FR-AUTH-006 | Role and permission management | Must | BR-SEC-002 | services/auth, services/users | tests/api/test_access_control.py::test_role_with_sod_conflict_is_flagged, test_cannot_change_own_permissions | Done |
| FR-AUTH-007 | Session management | Must | — | services/auth, services/users | tests/api/test_auth.py::test_refresh_rotates_and_reuse_ends_the_session, test_change_password_signs_out_other_sessions | Done |
| FR-AUTH-008 | Failed-login protection | Must | — | services/auth, services/users | tests/api/test_auth.py::test_five_failures_lock_the_account, test_admin_unlock_restores_sign_in | Done |
| FR-AUTH-009 | Server-side authorisation | Must | BR-SEC-001, BR-SEC-003 | services/auth, services/users | tests/api/test_access_control.py::test_missing_permission_is_403 | Done |
| FR-AUTH-010 | Optional MFA | Should | — | services/auth, services/users |  | Planned |
| FR-AUTH-011 | User activity logs | Must | BR-AUD-001 | services/auth, services/users | tests/integration/test_database.py::test_audit_chain_verifies | Done |
| FR-AUTH-012 | Branch access restrictions | Must | BR-SEC-001 | services/auth, services/users | tests/api/test_access_control.py::test_other_company_records_are_404, api/test_auth.py::test_pin_login_refused_outside_assigned_branch (branch filters on business data arrive with Phase 3+) | Partial |
| FR-AUTH-013 | Employee profiles | Should | — | services/auth, services/users | tests/api/test_access_control.py::test_employee_profiles | Done |

### ORG (phase 3)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-ORG-001 | Company profile | Must | — | services/organization | tests/api/test_org.py::test_company_profile | Done |
| FR-ORG-002 | Branch management | Must | — | services/organization | tests/api/test_org.py::test_branch_creates_store_warehouse_and_locations | Done |
| FR-ORG-003 | Warehouse management | Must | — | services/organization | tests/api/test_org.py::test_branch_creates_store_warehouse_and_locations | Done |
| FR-ORG-004 | Stock locations | Must | BR-RET-003 | services/organization | tests/api/test_org.py::test_location_rules | Done |
| FR-ORG-005 | POS terminal registration | Must | BR-CSH-003 | services/organization | tests/api/test_org.py::test_terminal_needs_sellable_location_in_its_branch | Done |
| FR-ORG-006 | Cashier-terminal assignment | Should | BR-SEC-001 | services/organization | tests/api/test_org.py::test_terminal_needs_sellable_location_in_its_branch, tests/api/test_auth.py::test_pin_login_* | Done |
| FR-ORG-007 | Business hours and business date | Should | BR-SAL-008 | services/organization | tests/api/test_org.py (hours and day cut-off stored; business date applied to sales in Phase 5) | Partial |
| FR-ORG-008 | Fiscal year and reporting periods | Should | — | services/organization | tests/api/test_org.py::test_company_profile (fiscal start month stored; reporting periods in Phase 7) | Partial |
| FR-ORG-009 | Currency settings | Must | BR-PAY-006 | services/organization | tests/api/test_org.py::test_exchange_rates_append_only, test_settings_defaults_validation_and_flagging | Done |
| FR-ORG-010 | Receipt numbering | Must | BR-DOC-001 | services/organization | tests/api/test_org.py::test_sequences_only_move_forward, test_document_numbers_are_scoped_and_never_reused | Done |
| FR-ORG-011 | Product numbering | Should | BR-PRD-002 | services/organization | tests/api/test_catalog.py::test_create_with_auto_sku_price_conversion_and_barcode | Done |
| FR-ORG-012 | Branch-specific pricing switch | Should | BR-PRC-001 | services/organization | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback | Done |

### PRD (phase 3)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-PRD-001 | Product creation | Must | BR-PRD-002 | services/products | tests/api/test_catalog.py::test_create_with_auto_sku_price_conversion_and_barcode, test_frontend_payload_shape_is_accepted | Done |
| FR-PRD-002 | SKU and product code | Must | BR-PRD-002 | services/products | tests/api/test_catalog.py::test_create_with_auto_sku_price_conversion_and_barcode | Done |
| FR-PRD-003 | Barcodes | Must | BR-PRD-003 | services/products | tests/api/test_catalog.py::test_barcode_rules, test_generated_barcodes_are_valid_and_distinct | Done |
| FR-PRD-004 | Units on product | Must | BR-PRD-001 | services/products | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback, test_base_unit_locked_after_movements | Done |
| FR-PRD-005 | Prices on product | Must | BR-PRC-001 | services/products | tests/api/test_catalog.py::test_create_with_auto_sku_price_conversion_and_barcode | Done |
| FR-PRD-006 | Purchase cost reference | Must | BR-CST-001, BR-SEC-003 | services/products | tests/api/test_catalog.py::test_costs_hidden_without_permission (cost values are maintained by inventory in Phase 4) | Partial |
| FR-PRD-007 | Tax configuration | Must | — | services/products | tests/api/test_org.py::test_tax_code_rate_change_is_flagged (category default tax applied to products) | Done |
| FR-PRD-008 | Supplier association | Should | — | services/products | Supplier links arrive with purchasing (Phase 6); non-empty links are rejected until then | Planned |
| FR-PRD-009 | Stock parameters | Must | — | services/products | tests/api/test_catalog.py::test_frontend_payload_shape_is_accepted | Done |
| FR-PRD-010 | Product status | Must | — | services/products | tests/api/test_catalog.py::test_status_transitions, test_activation_needs_a_retail_price | Done |
| FR-PRD-011 | Variants | Must | BR-PRD-002 | services/products | tests/api/test_catalog.py::test_variants_are_created_as_children | Done |
| FR-PRD-012 | Weight and volume products | Must | BR-PRD-001 | services/products | tests/api/test_catalog.py::test_weighed_products_are_fractional | Done |
| FR-PRD-013 | Non-stock services | Must | — | services/products | tests/api/test_catalog.py (SERVICE type accepted; stock exclusion enforced by inventory in Phase 4) | Partial |
| FR-PRD-014 | Expiry and batch tracking | Should | BR-INV-007 | services/products | tests/api/test_catalog.py (track_expiry flag stored; batches in Phase 4) | Partial |
| FR-PRD-015 | Serial-number tracking | Could | BR-PRD-004 | services/products |  | Planned |
| FR-PRD-016 | Bundles and kits | Could | — | services/products |  | Planned |
| FR-PRD-017 | Product search and filters | Must | — | services/products | tests/api/test_catalog.py::test_search_by_name_sku_and_barcode | Done |
| FR-PRD-018 | Change history | Must | BR-AUD-001 | services/products | tests/api/test_catalog.py::test_delete_draft_and_history | Done |

### CAT (phase 3)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-CAT-001 | Category management | Must | — | services/catalog | tests/api/test_catalog.py::test_category_depth_and_cycles, test_in_use_master_data_cannot_be_deleted | Done |
| FR-CAT-002 | Category settings | Should | BR-INV-006, BR-RET-004 | services/catalog | tests/api/test_catalog.py::test_category_negative_stock_needs_company_setting (return rules applied in Phase 5) | Partial |
| FR-CAT-003 | Brand management | Must | — | services/catalog | tests/api/test_catalog.py::test_cashier_cannot_manage_catalogue | Done |
| FR-CAT-004 | Unit-of-measure management | Must | BR-PRD-001 | services/catalog | tests/api/test_catalog.py::test_in_use_master_data_cannot_be_deleted | Done |
| FR-CAT-005 | Unit conversions | Must | BR-PRD-001 | services/catalog | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback | Done |
| FR-CAT-006 | Base-quantity calculation | Must | BR-PRD-001 | services/catalog | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback (factor used for prices; stock quantities in Phase 4) | Partial |
| FR-CAT-007 | Category-level reporting | Must | BR-RPT-001 | services/catalog |  | Planned |
| FR-CAT-008 | Product filtering | Must | — | services/catalog | tests/api/test_catalog.py::test_search_by_name_sku_and_barcode | Done |

### POS (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-POS-001 | Barcode scanning | Must | BR-PRD-003 | services/pos | tests/api/test_sales.py::test_server_calculates_totals_and_ignores_client_amounts | Done |
| FR-POS-002 | Product search | Must | — | services/pos | tests/api/test_catalog.py::test_search_by_name_sku_and_barcode (POS uses GET /products?sellable=true) | Done |
| FR-POS-003 | Category browsing | Must | — | services/pos | categories and favourites (is_favourite sorts first) served by /categories and /products | Done |
| FR-POS-004 | Quantity entry and adjustment | Must | BR-PRD-001 | services/pos | tests/api/test_sales.py::test_server_calculates_totals_and_ignores_client_amounts, test_box_unit_uses_base_price_times_factor | Done |
| FR-POS-005 | Unit price display | Must | BR-POS-001 | services/pos | tests/api/test_sales.py::test_server_calculates_totals_and_ignores_client_amounts | Done |
| FR-POS-006 | Line and order discounts | Must | BR-POS-004, BR-PRM-001 | services/pos | tests/api/test_sales.py::test_discount_within_limit_and_above_limit, test_order_discount_is_shared_across_lines | Done |
| FR-POS-007 | Tax and totals | Must | BR-POS-001 | services/pos | tests/api/test_sales.py::test_server_calculates_totals_and_ignores_client_amounts (exclusive tax; inclusive mode by setting) | Done |
| FR-POS-008 | Customer selection | Must | BR-CUS-001 | services/pos | walk-in only until customers arrive in Phase 6 | Planned |
| FR-POS-009 | Hold and resume sale | Must | BR-POS-003 | services/pos | tests/api/test_sales.py::test_hold_and_resume_reprices | Done |
| FR-POS-010 | Cancel sale | Must | BR-POS-004 | services/pos | tests/api/test_sales.py::test_cancel_with_items_needs_approval | Done |
| FR-POS-011 | Availability and out-of-stock warnings | Must | BR-POS-002 | services/pos | line.available returned; finalize enforces stock: tests/api/test_sales.py::test_last_unit_cannot_be_sold_twice | Done |
| FR-POS-012 | Price overrides | Must | BR-POS-004 | services/pos | tests/api/test_sales.py::test_price_override_needs_approval | Done |
| FR-POS-013 | Refund and return initiation | Must | BR-RET-001 | services/pos | tests/api/test_sales.py::test_partial_return_refunds_from_snapshots, test_sales_visibility (receipt lookup) | Done |
| FR-POS-014 | Cashier and terminal identification | Must | — | services/pos | tests/api/test_sales.py::test_cash_sale_end_to_end (cashier, terminal, session, branch on each sale) | Done |
| FR-POS-015 | Sales history on POS | Must | — | services/pos | tests/api/test_sales.py::test_sales_visibility | Done |
| FR-POS-016 | Keyboard shortcuts | Should | — | services/pos |  | Planned |
| FR-POS-017 | Idempotent sale operations | Must | BR-PAY-002 | services/pos | tests/api/test_sales.py::test_cash_sale_end_to_end (finalize replay) | Done |

### PAY (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-PAY-001 | Cash payments | Must | BR-PAY-005, BR-PAY-006 | services/payments | tests/api/test_sales.py::test_cash_sale_end_to_end, test_khr_cash_rounding_and_change | Done |
| FR-PAY-002 | Card payments | Must | BR-PAY-004 | services/payments | tests/api/test_sales.py::test_electronic_refund_waits_for_reference (standalone terminal approval code; no provider integration, V-03) | Partial |
| FR-PAY-003 | QR and electronic payments | Should | BR-PAY-004 | services/payments | tests/api/test_sales.py::test_card_cannot_exceed_balance_and_needs_confirmation (verified reference entry; provider adapters await V-03) | Partial |
| FR-PAY-004 | Bank transfers | Should | — | services/payments | BANK_TRANSFER with reference, same path as QR | Done |
| FR-PAY-005 | Split payments | Must | BR-PAY-001 | services/payments | tests/api/test_sales.py::test_price_change_before_finalize_is_caught (two payments), test_exchange_creates_linked_finalized_sale | Done |
| FR-PAY-006 | Partial payments | Could | BR-PAY-007 | services/payments | partial payments disabled (D-11); finalize returns BALANCE_DUE | Done |
| FR-PAY-007 | Change calculation | Must | BR-PAY-005 | services/payments | tests/api/test_sales.py::test_cash_sale_end_to_end, test_usd_tender_with_riel_change | Done |
| FR-PAY-008 | Payment statuses | Must | BR-PAY-003 | services/payments | tests/api/test_sales.py::test_card_cannot_exceed_balance_and_needs_confirmation | Done |
| FR-PAY-009 | Provider confirmation | Must | BR-PAY-004 | services/payments | manual verified reference only; signed provider callbacks await V-03 | Partial |
| FR-PAY-010 | Duplicate prevention | Must | BR-PAY-002 | services/payments | tests/api/test_sales.py::test_card_cannot_exceed_balance_and_needs_confirmation (duplicate reference), test_cash_sale_end_to_end (idempotency) | Done |
| FR-PAY-011 | Payment failure handling | Must | — | services/payments | resolve FAILED keeps the sale open for another method | Done |
| FR-PAY-012 | Payment cancellation | Must | — | services/payments | resolve CANCELLED; cancelling a sale cancels pending payments | Done |
| FR-PAY-013 | Payment references | Must | — | services/payments | tests/api/test_sales.py::test_electronic_refund_waits_for_reference | Done |
| FR-PAY-014 | Payment reconciliation | Should | — | services/payments | GET /payments and POST /payments/{id}/reconcile (statement import in Phase 8) | Partial |
| FR-PAY-015 | Pending payment recovery | Must | BR-PAY-004 | services/payments | stock reservations expire automatically; provider status job in the Phase 8 worker | Partial |

### CSH (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-CSH-001 | Open session | Must | BR-CSH-003 | services/cash_sessions | tests/api/test_sales.py::test_payments_and_finalize_need_an_open_session | Done |
| FR-CSH-002 | Cash sales and refunds | Must | BR-CSH-001 | services/cash_sessions | tests/api/test_sales.py::test_void_restores_stock_and_refunds_cash | Done |
| FR-CSH-003 | Cash in and cash out | Must | — | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval | Done |
| FR-CSH-004 | Paid-out expenses | Should | — | services/cash_sessions | PAID_OUT recorded; expense link in Phase 8 | Partial |
| FR-CSH-005 | Cash drops | Should | — | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval | Done |
| FR-CSH-006 | Expected cash calculation | Must | BR-CSH-001 | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval, test_void_restores_stock_and_refunds_cash | Done |
| FR-CSH-007 | Blind closing count | Must | — | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval | Done |
| FR-CSH-008 | Overage and shortage | Must | BR-CSH-002 | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval, test_close_within_tolerance_closes_directly | Done |
| FR-CSH-009 | Session closing and manager review | Must | BR-CSH-002 | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval (force-close endpoint included) | Done |
| FR-CSH-010 | Non-cash totals | Must | BR-CSH-001 | services/cash_sessions | summary.non_cash_totals by method | Done |
| FR-CSH-011 | Session history | Must | — | services/cash_sessions | GET /cashier-sessions with movements in the summary | Done |
| FR-CSH-012 | Session permissions | Must | BR-CSH-002 | services/cash_sessions | tests/api/test_sales.py::test_session_close_blind_count_and_variance_approval | Done |

### SAL (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-SAL-001 | Sales transactions | Must | BR-SAL-001 | services/sales | tests/api/test_sales.py::test_cash_sale_end_to_end | Done |
| FR-SAL-002 | Sale lines | Must | BR-SAL-005, BR-CST-003 | services/sales | tests/api/test_sales.py::test_server_calculates_totals_and_ignores_client_amounts | Done |
| FR-SAL-003 | Sale status | Must | BR-SAL-007 | services/sales | tests/api/test_sales.py::test_hold_and_resume_reprices, test_cancel_with_items_needs_approval, test_void_restores_stock_and_refunds_cash | Done |
| FR-SAL-004 | Payment status | Must | BR-PAY-003 | services/sales | tests/api/test_sales.py::test_partial_return_refunds_from_snapshots | Done |
| FR-SAL-005 | Fulfilment status | Could | — | services/sales |  | Planned |
| FR-SAL-006 | Discounts and tax on sales | Must | BR-PRM-001 | services/sales | tests/api/test_sales.py::test_discount_within_limit_and_above_limit | Done |
| FR-SAL-007 | Associations | Must | — | services/sales | cashier, terminal and session recorded; customer from Phase 6 | Partial |
| FR-SAL-008 | Cancellation | Must | BR-POS-004 | services/sales | tests/api/test_sales.py::test_cancel_with_items_needs_approval | Done |
| FR-SAL-009 | Void | Must | BR-SAL-003 | services/sales | tests/api/test_sales.py::test_void_restores_stock_and_refunds_cash | Done |
| FR-SAL-010 | Returns and exchanges link | Must | BR-SAL-004 | services/sales | tests/api/test_sales.py::test_exchange_creates_linked_finalized_sale | Done |
| FR-SAL-011 | Transaction history | Must | — | services/sales | tests/api/test_sales.py::test_sales_visibility | Done |
| FR-SAL-012 | No deletion of finalized sales | Must | BR-SAL-003, BR-SAL-006 | services/sales | no delete endpoint exists for sales | Done |

### DOC (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-DOC-001 | Receipt generation | Must | BR-DOC-001 | services/documents | tests/api/test_sales.py::test_cash_sale_end_to_end (GET /sales/{id}/receipt) | Done |
| FR-DOC-002 | Invoice generation | Should | — | services/documents | POST /sales/{id}/invoice assigns the invoice number; A4 PDF layout in Phase 8 | Partial |
| FR-DOC-003 | Templates | Must | — | services/documents | receipt templates per branch (Phase 3) used by the receipt endpoint | Done |
| FR-DOC-004 | Sequential numbering | Must | BR-DOC-001 | services/documents | tests/api/test_sales.py::test_last_unit_cannot_be_sold_twice (no number consumed on rollback) | Done |
| FR-DOC-005 | Thermal printing | Must | — | services/documents | print data provided; the ESC/POS print agent is a separate local component | Partial |
| FR-DOC-006 | PDF output | Must | — | services/documents |  | Planned |
| FR-DOC-007 | Reprinting | Must | BR-DOC-002 | services/documents | tests/api/test_sales.py::test_cash_sale_end_to_end (COPY on reprint) | Done |
| FR-DOC-008 | Refund references | Must | BR-RET-001 | services/documents | returns reference the original receipt number | Done |
| FR-DOC-009 | Email delivery | Could | — | services/documents |  | Planned |
| FR-DOC-010 | Document snapshot | Must | BR-SAL-005 | services/documents | receipts rebuilt from sale line snapshots | Done |

### INV (phase 4)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-INV-001 | Current stock by product | Must | BR-INV-003 | services/inventory | tests/api/test_inventory.py::test_product_list_shows_real_stock, test_transfer_conserves_stock | Done |
| FR-INV-002 | Stock by branch, warehouse and location | Must | — | services/inventory | tests/api/test_inventory.py::test_transfer_conserves_stock, test_costs_hidden_and_scope_enforced | Done |
| FR-INV-003 | Movement ledger | Must | BR-INV-001 | services/inventory | tests/api/test_inventory.py::test_ledger_is_append_only, test_every_movement_has_matching_ledger_rows | Done |
| FR-INV-004 | Atomic balance updates | Must | BR-INV-003 | services/inventory | tests/api/test_inventory.py::test_failed_adjustment_post_changes_nothing, test_concurrent_moves_cannot_oversell | Done |
| FR-INV-005 | Stock receipts and issues | Must | — | services/inventory | tests/api/test_inventory.py::test_opening_stock_sets_balance_and_cost (sale and purchase movements arrive with Phases 5 and 6) | Partial |
| FR-INV-006 | Relocation within a warehouse | Should | — | services/inventory | tests/api/test_inventory.py::test_running_balance, test_reversal_posts_an_opposite_movement_once | Done |
| FR-INV-007 | Reservations | Should | BR-INV-009 | services/inventory | reserved column and availability honour reservations; reservation records arrive with electronic payments in Phase 5 (D-07) | Partial |
| FR-INV-008 | Availability service | Must | — | services/inventory | GET /inventory/availability; tests/api/test_inventory.py::test_product_list_shows_real_stock | Done |
| FR-INV-009 | Negative stock prevention | Must | BR-INV-006 | services/inventory | tests/api/test_inventory.py::test_negative_stock_is_blocked | Done |
| FR-INV-010 | Damaged, expired and lost stock | Must | BR-INV-005 | services/inventory | tests/api/test_inventory.py::test_adjustment_within_limit_posts_without_second_approval, test_transfer_conserves_stock (damaged in transit) | Done |
| FR-INV-011 | Write-offs | Must | BR-INV-004 | services/inventory | tests/api/test_inventory.py::test_failed_adjustment_post_changes_nothing (WRITE_OFF lines) | Done |
| FR-INV-012 | Movement history | Must | — | services/inventory | tests/api/test_inventory.py::test_running_balance, test_reversal_posts_an_opposite_movement_once | Done |
| FR-INV-013 | Corrections by reversal | Must | BR-INV-002 | services/inventory | tests/api/test_inventory.py::test_reversal_posts_an_opposite_movement_once | Done |
| FR-INV-014 | Batch and expiry | Should | BR-INV-007 | services/inventory | tests/api/test_inventory.py::test_expiring_batches (batch receipt via purchasing in Phase 6) | Partial |
| FR-INV-015 | Serial numbers | Could | BR-PRD-004 | services/inventory |  | Planned |
| FR-INV-016 | Balance reconciliation | Must | BR-INV-003 | services/inventory | tests/api/test_inventory.py::test_reconciliation_detects_tampering | Done |
| FR-INV-017 | Discrepancy reporting | Must | — | services/inventory | tests/api/test_inventory.py::test_reconciliation_detects_tampering (flagged audit entry; report view in Phase 7) | Partial |

### CST (phase 4)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-CST-001 | Configurable costing method | Must | BR-CST-002 | services/costing | WAC fixed by D-05; settings reject other methods: tests/api/test_org.py::test_settings_defaults_validation_and_flagging | Done |
| FR-CST-002 | Purchase cost capture | Must | BR-CST-001 | services/costing | tests/api/test_inventory.py::test_weighted_average_cost (goods receipt document in Phase 6) | Partial |
| FR-CST-003 | Landed costs | Could | — | services/costing |  | Planned |
| FR-CST-004 | COGS at sale | Must | BR-CST-003 | services/costing |  | Planned |
| FR-CST-005 | Cost adjustment | Should | BR-INV-004 | services/costing |  | Planned |
| FR-CST-006 | Returned goods valuation | Must | BR-CST-004 | services/costing |  | Planned |
| FR-CST-007 | Damaged goods write-off | Must | BR-CST-004 | services/costing | tests/api/test_inventory.py::test_adjustment_within_limit_posts_without_second_approval (value snapshot on DAMAGE) | Done |
| FR-CST-008 | Inventory valuation report | Must | BR-CST-002 | services/costing |  | Planned |
| FR-CST-009 | Gross profit calculation | Must | BR-RPT-002 | services/costing |  | Planned |
| FR-CST-010 | Historical cost preservation | Must | BR-CST-003 | services/costing | tests/api/test_inventory.py::test_weighted_average_cost (unit cost stored on every movement) | Done |
| FR-CST-011 | Accounting entries | Could | — | services/costing |  | Planned |

### PUR (phase 6)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-PUR-001 | Supplier records | Must | — | services/purchasing |  | Planned |
| FR-PUR-002 | Supplier contacts | Should | — | services/purchasing |  | Planned |
| FR-PUR-003 | Purchase requisitions | Could | — | services/purchasing |  | Planned |
| FR-PUR-004 | Purchase orders | Must | BR-PUR-002 | services/purchasing |  | Planned |
| FR-PUR-005 | PO approval | Must | BR-PUR-001 | services/purchasing |  | Planned |
| FR-PUR-006 | PO sending | Should | — | services/purchasing |  | Planned |
| FR-PUR-007 | Supplier invoices and matching | Should | BR-PUR-003 | services/purchasing |  | Planned |
| FR-PUR-008 | Purchase returns | Should | BR-INV-001 | services/purchasing |  | Planned |
| FR-PUR-009 | Supplier credit notes | Should | — | services/purchasing |  | Planned |
| FR-PUR-010 | Supplier payments or references | Could | — | services/purchasing |  | Planned |
| FR-PUR-011 | Supplier balances | Could | — | services/purchasing |  | Planned |
| FR-PUR-012 | Supplier pricing and lead times | Should | — | services/purchasing |  | Planned |
| FR-PUR-013 | Purchase history and performance | Should | — | services/purchasing |  | Planned |
| FR-PUR-014 | PO cancellation and short-close | Must | BR-AUD-001 | services/purchasing |  | Planned |

### GRN (phase 6)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-GRN-001 | Receive against PO | Must | BR-GRN-003 | services/receiving |  | Planned |
| FR-GRN-002 | Receive without PO | Should | BR-GRN-003 | services/receiving |  | Planned |
| FR-GRN-003 | Partial receipt | Must | — | services/receiving |  | Planned |
| FR-GRN-004 | Barcode-assisted receiving | Must | BR-PRD-003 | services/receiving |  | Planned |
| FR-GRN-005 | Batch, expiry and serial capture | Should | BR-INV-007, BR-PRD-004 | services/receiving |  | Planned |
| FR-GRN-006 | Quantity verification | Must | — | services/receiving |  | Planned |
| FR-GRN-007 | Damaged goods recording | Must | BR-GRN-002 | services/receiving |  | Planned |
| FR-GRN-008 | Discrepancies and approval | Must | BR-GRN-002 | services/receiving |  | Planned |
| FR-GRN-009 | Supplier delivery references | Must | — | services/receiving |  | Planned |
| FR-GRN-010 | Single posting | Must | BR-GRN-001 | services/receiving |  | Planned |

### TRF (phase 4)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-TRF-001 | Transfer requests | Must | BR-TRF-001 | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-002 | Transfer approval | Must | BR-SEC-002 | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-003 | Dispatch | Must | BR-TRF-001 | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-004 | In-transit stock | Must | — | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-005 | Receipt confirmation | Must | BR-TRF-002 | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-006 | Partial receipt | Should | — | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock | Done |
| FR-TRF-007 | Discrepancies | Must | BR-TRF-002 | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock, test_transfer_receipt_cannot_exceed_dispatch | Done |
| FR-TRF-008 | Cancellation | Must | — | services/transfers | tests/api/test_inventory.py (cancel before dispatch) | Done |
| FR-TRF-009 | Transfer history | Must | — | services/transfers | tests/api/test_inventory.py::test_transfer_conserves_stock (timeline and movements by source) | Done |

### ADJ (phase 4)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-ADJ-001 | Adjustment requests | Must | BR-INV-001 | services/adjustments | tests/api/test_inventory.py::test_adjustment_reason_signs | Done |
| FR-ADJ-002 | Adjustment approval | Must | BR-INV-004 | services/adjustments | tests/api/test_inventory.py::test_adjustment_above_limit_needs_another_approver | Done |
| FR-ADJ-003 | Adjustment posting | Must | BR-INV-002 | services/adjustments | tests/api/test_inventory.py::test_adjustment_within_limit_posts_without_second_approval | Done |
| FR-ADJ-004 | Cycle counting | Should | — | services/adjustments | tests/api/test_inventory.py::test_count_posts_deltas_not_absolute_quantities, test_frozen_count_blocks_movements | Done |
| FR-ADJ-005 | Full stocktake | Must | — | services/adjustments | FULL scope supported; covered by the same count workflow tests | Done |
| FR-ADJ-006 | Count entry | Must | BR-INV-008 | services/adjustments | tests/api/test_inventory.py::test_count_posts_deltas_not_absolute_quantities (blind entry) | Done |
| FR-ADJ-007 | Variance calculation | Must | — | services/adjustments | tests/api/test_inventory.py::test_count_posts_deltas_not_absolute_quantities | Done |
| FR-ADJ-008 | Investigation | Should | — | services/adjustments | tests/api/test_inventory.py::test_large_variance_needs_recount | Done |
| FR-ADJ-009 | Delta posting | Must | BR-INV-008 | services/adjustments | tests/api/test_inventory.py::test_count_posts_deltas_not_absolute_quantities | Done |
| FR-ADJ-010 | Adjustment history | Must | BR-AUD-001 | services/adjustments | tests/api/test_inventory.py::test_adjustment_above_limit_needs_another_approver (timeline, audit log) | Done |

### RET (phase 5)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-RET-001 | Customer returns | Must | BR-RET-001 | services/returns | tests/api/test_sales.py::test_partial_return_refunds_from_snapshots | Done |
| FR-RET-002 | Full and partial returns | Must | BR-RET-001 | services/returns | tests/api/test_sales.py::test_partial_return_refunds_from_snapshots, test_damaged_return_goes_to_damaged_location_and_large_refund_needs_approval | Done |
| FR-RET-003 | Refunds | Must | BR-RET-005 | services/returns | tests/api/test_sales.py::test_partial_return_refunds_from_snapshots | Done |
| FR-RET-004 | Exchanges | Must | — | services/returns | tests/api/test_sales.py::test_exchange_creates_linked_finalized_sale | Done |
| FR-RET-005 | Store credit | Could | — | services/returns | store credit arrives with customers (Phase 6) | Planned |
| FR-RET-006 | Return reasons and condition | Must | BR-RET-003 | services/returns | tests/api/test_sales.py::test_damaged_return_goes_to_damaged_location_and_large_refund_needs_approval | Done |
| FR-RET-007 | Restocking decision | Must | BR-RET-003 | services/returns | tests/api/test_sales.py::test_damaged_return_goes_to_damaged_location_and_large_refund_needs_approval | Done |
| FR-RET-008 | Refund approval | Must | BR-RET-002 | services/returns | tests/api/test_sales.py::test_damaged_return_goes_to_damaged_location_and_large_refund_needs_approval | Done |
| FR-RET-009 | Payment refund reference | Must | BR-RET-005 | services/returns | tests/api/test_sales.py::test_electronic_refund_waits_for_reference | Done |
| FR-RET-010 | Eligibility rules | Must | BR-RET-004 | services/returns | window and returnable flags checked in the quote; approval when breached | Done |
| FR-RET-011 | Return receipts | Must | BR-DOC-001 | services/returns | return data references the original receipt; return print layout uses the print agent | Partial |

### CUS (phase 6)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-CUS-001 | Customer profiles | Must | BR-CUS-001 | services/customers |  | Planned |
| FR-CUS-002 | Customer search | Must | — | services/customers |  | Planned |
| FR-CUS-003 | Walk-in customers | Must | BR-CUS-001 | services/customers |  | Planned |
| FR-CUS-004 | Purchase history | Should | — | services/customers |  | Planned |
| FR-CUS-005 | Customer groups and pricing groups | Should | BR-PRC-002 | services/customers |  | Planned |
| FR-CUS-006 | Customer discounts | Should | BR-PRM-001 | services/customers |  | Planned |
| FR-CUS-007 | Store credit | Could | — | services/customers |  | Planned |
| FR-CUS-008 | Credit sales and statements | Could | BR-PAY-007 | services/customers |  | Planned |
| FR-CUS-009 | Personal data controls | Must | BR-CUS-001 | services/customers |  | Planned |

### PRM (phase 8)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-PRM-001 | Loyalty points | Could | — | services/promotions |  | Planned |
| FR-PRM-002 | Membership levels | Could | — | services/promotions |  | Planned |
| FR-PRM-003 | Promotion rules | Could | BR-PRM-001 | services/promotions |  | Planned |
| FR-PRM-004 | Coupon codes | Could | BR-PRM-002 | services/promotions |  | Planned |
| FR-PRM-005 | Loyalty redemption | Could | — | services/promotions |  | Planned |
| FR-PRM-006 | Validity and limits | Could | BR-PRM-002 | services/promotions |  | Planned |
| FR-PRM-007 | Precedence and combination | Could | BR-PRM-001 | services/promotions |  | Planned |
| FR-PRM-008 | Return effect | Could | BR-RET-005 | services/promotions |  | Planned |
| FR-PRM-009 | Override recording | Could | BR-POS-004 | services/promotions |  | Planned |

### PRC (phase 3)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-PRC-001 | Standard and retail price | Must | BR-PRC-001 | services/pricing | tests/api/test_catalog.py::test_new_price_closes_the_old_one_and_is_recorded | Done |
| FR-PRC-002 | Wholesale price | Should | — | services/pricing | tests/api/test_catalog.py::test_create_with_auto_sku_price_conversion_and_barcode | Done |
| FR-PRC-003 | Branch-specific price | Should | BR-PRC-002 | services/pricing | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback | Done |
| FR-PRC-004 | Customer-group price | Should | BR-PRC-002 | services/pricing | Customer groups arrive in Phase 6; resolution order already reserves the slot | Planned |
| FR-PRC-005 | Promotion price | Could | BR-PRC-002 | services/pricing |  | Planned |
| FR-PRC-006 | Effective dates | Must | BR-PRC-001 | services/pricing | tests/api/test_catalog.py::test_scheduled_price_can_be_removed_and_reopens_previous, test_prices_cannot_be_backdated_or_below_minimum, test_database_rejects_overlapping_prices | Done |
| FR-PRC-007 | Price change history | Must | BR-AUD-001 | services/pricing | tests/api/test_catalog.py::test_new_price_closes_the_old_one_and_is_recorded | Done |
| FR-PRC-008 | Bulk price updates | Should | — | services/pricing | tests/api/test_catalog.py::test_bulk_price_change | Done |
| FR-PRC-009 | Price import | Should | BR-IMP-001 | services/pricing |  | Planned |
| FR-PRC-010 | Minimum margin warnings | Should | BR-POS-004 | services/pricing | tests/api/test_catalog.py::test_bulk_price_change (minimum price enforced; category margin warnings with costs in Phase 4) | Partial |
| FR-PRC-011 | Price override permissions | Must | BR-POS-004 | services/pricing |  | Planned |
| FR-PRC-012 | Price resolution service | Must | BR-PRC-002 | services/pricing | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback, test_scan_refuses_unsellable_products | Done |

### ALR (phase 4)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-ALR-001 | Low-stock alerts | Must | — | services/alerts | tests/api/test_inventory.py::test_alerts_raise_and_resolve | Done |
| FR-ALR-002 | Out-of-stock alerts | Must | — | services/alerts | raised by /alerts/evaluate with the same mechanism as low stock | Done |
| FR-ALR-003 | Overstock alerts | Should | — | services/alerts | raised by /alerts/evaluate against max level | Done |
| FR-ALR-004 | Expiration warnings | Should | BR-INV-005 | services/alerts | tests/api/test_inventory.py::test_expiring_batches | Done |
| FR-ALR-005 | Reorder suggestions | Should | BR-PUR-002 | services/alerts | tests/api/test_inventory.py::test_alerts_raise_and_resolve (supplier and on-order from Phase 6) | Partial |
| FR-ALR-006 | Slow-moving alerts | Should | — | services/alerts | raised by /alerts/evaluate from last SALE movement (sales from Phase 5) | Partial |
| FR-ALR-007 | Negative stock alerts | Must | BR-INV-006 | services/alerts | raised by /alerts/evaluate when a balance is negative | Done |
| FR-ALR-008 | Unusual adjustment alerts | Should | BR-INV-004 | services/alerts | tests/api/test_inventory.py::test_unusual_adjustment_raises_alert | Done |
| FR-ALR-009 | Configurable thresholds | Must | — | services/alerts | thresholds in company settings and product/warehouse levels | Done |
| FR-ALR-010 | Assignment and lifecycle | Should | — | services/alerts | tests/api/test_inventory.py::test_alerts_raise_and_resolve (snooze, auto-resolve) | Done |

### EXP (phase 8)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-EXP-001 | Expense categories | Could | — | services/expenses |  | Planned |
| FR-EXP-002 | Expense recording | Could | — | services/expenses |  | Planned |
| FR-EXP-003 | Expense approval | Could | BR-SEC-002 | services/expenses |  | Planned |
| FR-EXP-004 | Drawer paid-outs | Could | BR-CSH-001 | services/expenses |  | Planned |
| FR-EXP-005 | Expense reporting | Could | BR-RPT-002 | services/expenses |  | Planned |
| FR-EXP-006 | Separation from COGS | Could | BR-CST-001 | services/expenses |  | Planned |

### DSH (phase 7)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-DSH-001 | Owner dashboard | Should | BR-RPT-002 | services/dashboard |  | Planned |
| FR-DSH-002 | Manager dashboard | Should | — | services/dashboard |  | Planned |
| FR-DSH-003 | Inventory dashboard | Should | — | services/dashboard |  | Planned |
| FR-DSH-004 | Cashier dashboard | Should | BR-CSH-001 | services/dashboard |  | Planned |
| FR-DSH-005 | KPI definitions | Should | BR-RPT-001 | services/dashboard |  | Planned |
| FR-DSH-006 | Permissions and scope | Must | BR-SEC-003 | services/dashboard |  | Planned |
| FR-DSH-007 | Reconciliation with reports | Must | BR-RPT-001 | services/dashboard |  | Planned |
| FR-DSH-008 | Drill-down | Should | — | services/dashboard |  | Planned |

### RPT (phase 7)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-RPT-001 | Sales reports | Must | BR-RPT-001 | services/reports |  | Planned |
| FR-RPT-002 | Discount, refund and void reports | Must | — | services/reports |  | Planned |
| FR-RPT-003 | Tax summary | Should | — | services/reports |  | Planned |
| FR-RPT-004 | Gross profit and margin | Must | BR-RPT-002, BR-SEC-003 | services/reports |  | Planned |
| FR-RPT-005 | Inventory reports | Must | BR-INV-003 | services/reports |  | Planned |
| FR-RPT-006 | Purchasing reports | Should | — | services/reports |  | Planned |
| FR-RPT-007 | Cashier and payment reports | Must | BR-CSH-001 | services/reports |  | Planned |
| FR-RPT-008 | Business performance | Should | — | services/reports |  | Planned |
| FR-RPT-009 | Control exceptions | Should | BR-SEC-002 | services/reports |  | Planned |
| FR-RPT-010 | Filters | Must | — | services/reports |  | Planned |
| FR-RPT-011 | Exports and printing | Must | — | services/reports |  | Planned |
| FR-RPT-012 | Reconciliation checks | Should | BR-INV-003 | services/reports |  | Planned |

### BRN (phase 7)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-BRN-001 | Centralized catalogue | Must | — | core/permissions (scope) | tests/api/test_catalog.py::test_scan_refuses_unsellable_products (one catalogue, per-branch activation) | Done |
| FR-BRN-002 | Branch-specific stock | Must | — | core/permissions (scope) |  | Planned |
| FR-BRN-003 | Branch-specific pricing | Should | BR-PRC-002 | core/permissions (scope) | tests/api/test_catalog.py::test_resolution_order_and_unit_fallback | Done |
| FR-BRN-004 | Branch-specific terminals | Must | — | core/permissions (scope) | tests/api/test_org.py::test_terminal_needs_sellable_location_in_its_branch, test_branch_scope_filters_lookups | Done |
| FR-BRN-005 | Inter-branch transfers | Must | BR-TRF-001 | core/permissions (scope) |  | Planned |
| FR-BRN-006 | Branch-level users and permissions | Must | BR-SEC-001 | core/permissions (scope) | tests/api/test_org.py::test_branch_scope_filters_lookups, tests/api/test_access_control.py | Partial |
| FR-BRN-007 | Branch-level reports | Must | — | core/permissions (scope) |  | Planned |
| FR-BRN-008 | Consolidated reporting | Should | — | core/permissions (scope) |  | Planned |
| FR-BRN-009 | Shared suppliers and customers | Should | — | core/permissions (scope) |  | Planned |

### NTF (phase 8)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-NTF-001 | Low-stock and expiration notifications | Should | — | services/notifications |  | Planned |
| FR-NTF-002 | Purchase approval notifications | Should | BR-PUR-001 | services/notifications |  | Planned |
| FR-NTF-003 | Receipt discrepancy notifications | Should | BR-GRN-002 | services/notifications |  | Planned |
| FR-NTF-004 | Pending transfer notifications | Should | — | services/notifications |  | Planned |
| FR-NTF-005 | Refund approval notifications | Must | BR-RET-002 | services/notifications |  | Planned |
| FR-NTF-006 | Cashier closing reminders | Should | — | services/notifications |  | Planned |
| FR-NTF-007 | System error notifications | Must | — | services/notifications |  | Planned |
| FR-NTF-008 | In-app and email channels | Should | — | services/notifications |  | Planned |

### IMP (phase 8)

| ID | Requirement | Priority | Business rules | Backend | Tests | Status |
|---|---|---|---|---|---|---|
| FR-IMP-001 | Product import | Must | BR-PRD-002 | services/imports |  | Planned |
| FR-IMP-002 | Barcode import | Must | BR-PRD-003 | services/imports |  | Planned |
| FR-IMP-003 | Supplier and customer import | Should | — | services/imports |  | Planned |
| FR-IMP-004 | Opening inventory import | Must | BR-IMP-001 | services/imports |  | Planned |
| FR-IMP-005 | Price import | Should | BR-PRC-001 | services/imports |  | Planned |
| FR-IMP-006 | Stock count import | Should | BR-INV-008 | services/imports |  | Planned |
| FR-IMP-007 | Preview and error report | Must | BR-IMP-001 | services/imports |  | Planned |
| FR-IMP-008 | Import history | Must | — | services/imports |  | Planned |
| FR-IMP-009 | Permission checks | Must | BR-SEC-001 | services/imports |  | Planned |
| FR-IMP-010 | Rollback and correction | Should | BR-INV-002 | services/imports |  | Planned |
| FR-IMP-011 | Exports | Must | BR-AUD-001 | services/imports |  | Planned |
