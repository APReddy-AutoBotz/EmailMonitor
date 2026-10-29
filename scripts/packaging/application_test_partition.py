"""Closed hosted test partitions and a stdlib-only, fail-closed cross-job join."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[2]
OUTCOME = (
    "services/backend/tests/test_job_outcome_investigation_tenant.py::"
    "test_actual_more_than_100_outcomes_have_no_omissions_or_duplicates"
)
RETAINED_SQL = (
    OUTCOME,
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_presence_pages_partition_before_limit_and_item_is_exact"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_item_api_foreign_missing_nonarticle_and_legacy_sql_acl"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_review_rejection_does_not_remove_observed_candidate"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_export_preview_membership_filter_idempotency_and_legacy_defaults"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_second_continuation_uses_original_batch_and_child_authority"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[deletion-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[retention-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-preview_create]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-claim_finish]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_filter_export_current_authority_races[suppression-ready_download]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_missing_unsealed_expired_and_mismatched_binding_is_unresolved"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[observed-True-observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[partial-True-observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[partial-False-unresolved]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[unsupported-False-unresolved]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_bound_xml_presence_independent_of_execution[no_contact-False-completed_without_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_sql_presence_null_and_inconsistent_profiles_fail_closed"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_ready_artifact_loses_its_source_classification[observed_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_tenant.py::"
        "test_actual_ready_artifact_loses_its_source_classification[completed_without_candidate]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_no_contact_and_inherited_contacts_only[False]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_no_contact_and_inherited_contacts_only[True]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[selected_deletion]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[source_deletion]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[retention]"
    ),
    (
        "services/backend/tests/test_retained_article_filters_service_tenant.py::"
        "test_actual_worker_filtered_authority_changes_between_claim_and_finish[revocation]"
    ),
)
# Exact authored-PDF cases share the existing SQL job; every case remains required.
PDF_ACCEPTANCE = (
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-ambiguous.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-article-a.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-article-b.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-corrupt.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-encrypted.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-no-contact.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-page-cap.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-scanned.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[False-wrapped.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-ambiguous.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-article-a.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-article-b.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-corrupt.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-encrypted.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-no-contact.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-page-cap.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-scanned.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_byte_capability_uses_s"
        "upervisor_image_without_gateway[True-wrapped.pdf]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[image]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[command]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[tenant]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[extra]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[unknown]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[digest]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[body]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_supervisor_rejects_unregis"
        "tered_pdf_requests_before_parser[kind]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_client_rejects_cross_r"
        "equest_or_cross_profile_response[id]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_client_rejects_cross_r"
        "equest_or_cross_profile_response[kind]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_channel.py::test_pdf_client_rejects_cross_r"
        "equest_or_cross_profile_response[observation]"
    ),
    (
        "services/backend/tests/test_controlled_pdf_tenant.py::test_actual_controlled_pdf_durab"
        "le_replay_review_export"
    ),
    (
        "services/backend/tests/test_controlled_pdf_tenant.py::test_actual_controlled_pdf_cance"
        "l_after_parse_cannot_commit"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[am"
        "biguous.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[ar"
        "ticle-a.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[ar"
        "ticle-b.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[co"
        "rrupt.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[en"
        "crypted.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[no"
        "-contact.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[pa"
        "ge-cap.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[sc"
        "anned.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_actual_pdf_durable_journey[wr"
        "apped.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[ambiguous.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[article-a.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[article-b.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[corrupt.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[encrypted.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[no-contact.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[page-cap.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[scanned.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_retention_review_and_"
        "export[wrapped.pdf]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_existing_policy_does_not_gain"
        "_pdf_access"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_disabled_or_unknown_pdf_does_"
        "not_plan[article-a.pdf-False]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_disabled_or_unknown_pdf_does_"
        "not_plan[unknown.pdf-True]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[cancel]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[pause]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[delete]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[retention]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[expired_lease]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[lost_lease]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[revoked_policy]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[expired_session]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_pdf_current_fences_reject_com"
        "mit_after_parser[revoked_session]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[cancel]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[pause]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[delete]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[retention]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[expired_lease]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[lost_lease]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[revoked_policy]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[expired_session]"
    ),
    (
        "services/backend/tests/test_pdf_pipeline_tenant.py::test_sql_pdf_commit_rechecks_curre"
        "nt_authority[revoked_session]"
    ),
)
# Measured SQL/broker work shares the existing isolated SQL job and its unchanged budget.
SERVICE_SQL = (
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_busy_r"
        "ow_defers_without_send_or_receipt[job]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_busy_r"
        "ow_defers_without_send_or_receipt[item]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_busy_r"
        "ow_defers_without_send_or_receipt[outbox]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_confir"
        "m_busy_row_remains_fatal[job]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_confir"
        "m_busy_row_remains_fatal[item]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_confir"
        "m_busy_row_remains_fatal[outbox]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_revoca"
        "tion_after_enumeration_is_not_busy_defer[origin]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publication_revoca"
        "tion_after_enumeration_is_not_busy_defer[delegation]"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_real_installed_wor"
        "ker_survives_human_expiry_and_restart"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_real_export_publis"
        "h_claim_race_recovers_without_manual_delivery"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_real_post_observat"
        "ion_crash_original_redelivery_then_lease_recovery"
    ),
    (
        "services/backend/tests/test_service_runtime_broker.py::test_service_publisher_skips_in"
        "eligible_older_resource_before_limit"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_login_scope"
        "_and_human_pool_separation"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_natural_exp"
        "iry_then_explicit_origin_revocation"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_forged_scop"
        "e_and_rolled_back_pool[organization]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_forged_scop"
        "e_and_rolled_back_pool[resource]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_forged_scop"
        "e_and_rolled_back_pool[purpose]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_forged_scop"
        "e_and_rolled_back_pool[generation]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_no_direct_a"
        "uthority_or_human_management_access"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_principal_d"
        "isable_enable_never_revives_delegation"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_duplicate_d"
        "elegation_preserves_deadline"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_extraction_"
        "without_human_session_and_current_logout_fence"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_human_work_audit_preserv"
        "es_event_and_resource_semantics[discovery.planned]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_human_work_audit_preserv"
        "es_event_and_resource_semantics[discovery.page_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_human_work_audit_preserv"
        "es_event_and_resource_semantics[discovery.delivery.received]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_human_work_audit_preserv"
        "es_event_and_resource_semantics[extraction.observation_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[current-discovery.page_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[current-extraction.observation_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[missing-discovery.page_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[missing-extraction.observation_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[stale-discovery.page_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[stale-extraction.observation_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[wrong_resource-discovery.page_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_requi"
        "res_current_exact_lease[wrong_resource-extraction.observation_committed]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_refus"
        "es_actions_outside_commit_subset[None]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_refus"
        "es_actions_outside_commit_subset[discovery.planned]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_refus"
        "es_actions_outside_commit_subset[discovery.delivery.received]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_audit_refus"
        "es_actions_outside_commit_subset[arbitrary.audit]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_logout_afte"
        "r_observation_prevents_association_and_effect"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_known_human"
        "_hash_cannot_escape_service_login[owner]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_known_human"
        "_hash_cannot_escape_service_login[owner_b]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_unleased_di"
        "scovery_mutation_denied"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_export_sepa"
        "rate_scope_and_exact_snapshot"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_legacy_rest"
        "ore_refuses_authority_without_revocation_seal"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_export_claim_has"
        "_sql_bounded_wait_and_post_wait_fence[fast_release]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_export_claim_has"
        "_sql_bounded_wait_and_post_wait_fence[timeout]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_export_claim_has"
        "_sql_bounded_wait_and_post_wait_fence[expiry]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_excess_logi"
        "n_privilege_refuses_new_and_existing_pool[CREATEROLE]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_excess_logi"
        "n_privilege_refuses_new_and_existing_pool[CREATEDB]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_excess_logi"
        "n_privilege_refuses_new_and_existing_pool[REPLICATION]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_reference_service_unsupp"
        "orted_provider_start_rolls_back_atomically[provider]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_reference_service_unsupp"
        "orted_provider_start_rolls_back_atomically[pdf]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_direct_auth"
        "enticator_privilege_invalidates_existing_pool"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_indirect_pr"
        "ivilege_change_invalidates_open_pool[expected_group]"
    ),
    (
        "services/backend/tests/test_service_authority_tenant.py::test_service_real_indirect_pr"
        "ivilege_change_invalidates_open_pool[custom_group_set_false]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_container_output_persi"
        "sts_review_and_both_exports"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_xml_no_excerpt_policy_"
        "never_accepts"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[cancel]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[pause]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[delete]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[suppression]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[retention]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[expired_lease]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[lost_lease]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[revoked_policy]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[revoked_session]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_parser_result_cannot_c"
        "ommit_after_authority_changes[expired_session]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[organization]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[job]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[item]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[generation]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[deletion_generation]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[policy_version]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_result_binding_mismatc"
        "h_refused[discovery_revision]"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_xml_requires_explicit_operati"
        "on_and_xml_only_refuses_html"
    ),
    ("services/backend/tests/test_xml_pipeline_tenant.py::test_html_policy_cannot_plan_xml"),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_actual_committed_xml_recovers"
        "_after_lost_completion"
    ),
    (
        "services/backend/tests/test_xml_pipeline_tenant.py::test_preparse_authority_refusal_ne"
        "ver_reads_xml_bytes"
    ),
)
# Exact timing/authority cases move to the existing SQL partition; none are omitted.
TIMING_SQL = (
    "services/backend/tests/test_job_timing_tenant.py::test_real_terminal_interval_replay_and_tenant_refusal",
    "services/backend/tests/test_job_timing_tenant.py::test_real_pause_resume_cancel_preserves_first_queue",
    "services/backend/tests/test_job_timing_tenant.py::test_real_continuation_has_own_interval_without_rewriting_original",
    "services/backend/tests/test_job_timing_tenant.py::test_real_expired_execution_refuses_timing",
    "services/backend/tests/test_progress_tenant.py::test_real_current_authorization_closes_replay_and_all_progress_tables[policy]",
    "services/backend/tests/test_progress_tenant.py::test_real_current_authorization_closes_replay_and_all_progress_tables[membership]",
    "services/backend/tests/test_progress_tenant.py::test_real_current_authorization_closes_replay_and_all_progress_tables[deletion]",
)
RESERVED_SQL = (*RETAINED_SQL, *PDF_ACCEPTANCE, *SERVICE_SQL, *TIMING_SQL)
PROFILES = ("backend", "outcome_sql")
ARGUMENTS = (
    "-c",
    "services/backend/pyproject.toml",
    "--rootdir=.",
    "-o",
    "addopts=",
    "-p",
    "anyio.pytest_plugin",
    "services/backend/tests",
    "tests",
)
OVERRIDES = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTHONPATH",
)
COMMON = ("source_tree", "config", "full", "backend", "outcome_sql")


class PartitionRefused(RuntimeError):
    """No selectors, arbitrary commands or partial execution can satisfy a gate."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def manifest(nodes: Sequence[str]) -> dict[str, str | int]:
    return {"count": len(nodes), "sha256": digest(sorted(nodes))}


def partitions(nodes: Sequence[str]) -> dict[str, list[str]]:
    full = Counter(nodes)
    if (
        not full
        or any(count != 1 for count in full.values())
        or any(full[node] != 1 for node in RESERVED_SQL)
        or any(
            not node.startswith(("services/backend/tests/", "tests/")) or "::" not in node
            for node in full
        )
    ):
        raise PartitionRefused("application_collection_refused")
    result = {
        "backend": [node for node in nodes if node not in RESERVED_SQL],
        "outcome_sql": [node for node in nodes if node in RESERVED_SQL],
    }
    backend, outcome = (Counter(result[key]) for key in PROFILES)
    if not backend or backend & outcome or backend + outcome != full:
        raise PartitionRefused("application_partition_refused")
    return result


def source_tree() -> str:
    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=ROOT, timeout=10).decode().strip()

    if git("status", "--porcelain", "--untracked-files=all"):
        raise PartitionRefused("application_source_dirty")
    tree = git("rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[a-f0-9]{40}", tree):
        raise PartitionRefused("application_source_refused")
    return tree


def configuration() -> str:
    return digest(
        {
            "arguments": ARGUMENTS,
            "autoload": False,
            "files": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "services/backend/pyproject.toml",
                    "services/backend/uv.lock",
                )
            },
        }
    )


class PartitionProof:
    def __init__(self, profile: str) -> None:
        if profile not in PROFILES:
            raise PartitionRefused("application_profile_refused")
        self.profile = profile
        self.discovered: list[str] = []
        self.full: list[str] = []
        self.assigned: dict[str, list[str]] = {}
        self.deselected: list[str] = []
        self.reports: Counter[tuple[str, str, str]] = Counter()
        self.collection_complete = False
        self.invalid = False

    def pytest_configure(self, config: pytest.Config) -> None:
        if config.invocation_params.args != ARGUMENTS:
            raise PartitionRefused("application_pytest_arguments_refused")

    def pytest_itemcollected(self, item: pytest.Item) -> None:
        self.discovered.append(item.nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.outcome != "passed":
            self.invalid = True

    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        self.full = [item.nodeid for item in items]
        if self.assigned or Counter(self.full) != Counter(self.discovered) or self.deselected:
            raise PartitionRefused("application_collection_changed")
        self.assigned = partitions(self.full)
        selected = set(self.assigned[self.profile])
        excluded = [item for item in items if item.nodeid not in selected]
        items[:] = [item for item in items if item.nodeid in selected]
        config.hook.pytest_deselected(items=excluded)

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if (
            not self.assigned
            or Counter(item.nodeid for item in session.items)
            != Counter(self.assigned[self.profile])
            or Counter(self.deselected) != Counter(self.assigned[self.other])
            or Counter(self.discovered) != Counter(self.full)
        ):
            raise PartitionRefused("application_selection_changed")
        self.collection_complete = True

    @property
    def other(self) -> str:
        return "outcome_sql" if self.profile == "backend" else "backend"

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports[report.nodeid, report.when, report.outcome] += 1
        if hasattr(report, "wasxfail"):
            self.invalid = True

    def receipt(self, code: int, tree: str, config: str) -> dict[str, Any]:
        expected = Counter(
            (node, phase, "passed")
            for node in self.assigned.get(self.profile, [])
            for phase in ("setup", "call", "teardown")
        )
        if code != 0 or self.invalid or not self.collection_complete or self.reports != expected:
            raise PartitionRefused("application_execution_incomplete")
        return {
            "schema": 1,
            "profile": self.profile,
            "source_tree": tree,
            "config": config,
            "full": manifest(self.full),
            **{profile: manifest(self.assigned[profile]) for profile in PROFILES},
            "executed": manifest(self.assigned[self.profile]),
            "deselected": manifest(self.deselected),
            "skipped": 0,
        }


def run(profile: str, environment: Mapping[str, str]) -> dict[str, Any]:
    if any(environment.get(key) for key in OVERRIDES):
        raise PartitionRefused("application_pytest_override_refused")
    proof = PartitionProof(profile)
    tree, config = source_tree(), configuration()
    # Keep exactly the existing pinned AnyIO plugin, without ambient entry points.
    # Set before importing pytest; no user-supplied argv reaches pytest.main.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest

    os.chdir(ROOT)
    from backend_outcome import KEY, Progress

    path = environment.get(KEY)
    diagnostics: list[Any] = [Progress(Path(path))] if path else []
    if profile == "backend":
        try:
            from backend_detail import KEY as DETAIL_KEY
            from backend_detail import Detail, owned_path

            detail_path = owned_path(path, environment.get(DETAIL_KEY))
            if detail_path is not None:
                diagnostics.append(Detail(detail_path))
        except Exception:
            pass  # Diagnostic installation cannot alter acceptance.
    code = pytest.main(list(ARGUMENTS), plugins=[proof, *diagnostics])
    if source_tree() != tree or configuration() != config:
        raise PartitionRefused("application_source_changed")
    return proof.receipt(int(code), tree, config)


def decode_receipt(raw: str, profile: str) -> dict[str, Any]:
    if len(raw) > 4096:
        raise PartitionRefused("application_receipt_refused")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PartitionRefused("application_receipt_refused")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "profile", *COMMON, "executed", "deselected", "skipped"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["profile"] != profile
        or type(value["skipped"]) is not int
        or value["skipped"] != 0
    ):
        raise PartitionRefused("application_receipt_refused")
    for key, length in (("source_tree", 40), ("config", 64)):
        if not isinstance(value[key], str) or not re.fullmatch(
            rf"[a-f0-9]{{{length}}}", value[key]
        ):
            raise PartitionRefused("application_receipt_refused")
    for key in ("full", *PROFILES, "executed", "deselected"):
        entry = value[key]
        if (
            not isinstance(entry, dict)
            or set(entry) != {"count", "sha256"}
            or type(entry["count"]) is not int
            or not 0 < entry["count"] < 1_000_000
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            raise PartitionRefused("application_receipt_refused")
    other = "outcome_sql" if profile == "backend" else "backend"
    if (
        value["outcome_sql"] != manifest(RESERVED_SQL)
        or value["full"]["count"] != value["backend"]["count"] + value["outcome_sql"]["count"]
        or value["executed"] != value[profile]
        or value["deselected"] != value[other]
    ):
        raise PartitionRefused("application_receipt_refused")
    return value


def join(environment: Mapping[str, str]) -> None:
    if any(
        environment.get(key) != "success"
        for key in ("BACKEND_RESULT", "OUTCOME_SQL_RESULT", "STATIC_RESULT")
    ):
        raise PartitionRefused("application_dependency_failed")
    backend = decode_receipt(environment.get("BACKEND_RECEIPT", ""), "backend")
    outcome = decode_receipt(environment.get("OUTCOME_SQL_RECEIPT", ""), "outcome_sql")
    if (
        any(backend[key] != outcome[key] for key in COMMON)
        or backend["source_tree"] != source_tree()
        or backend["config"] != configuration()
    ):
        raise PartitionRefused("application_receipts_differ")


def main(arguments: Sequence[str]) -> int:
    try:
        if len(arguments) != 1:
            raise PartitionRefused("application_arguments_refused")
        if arguments[0] == "join":
            join(os.environ)
        elif arguments[0] in PROFILES:
            receipt = run(arguments[0], os.environ)
            encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            output = os.environ.get("GITHUB_OUTPUT")
            if not output:
                raise PartitionRefused("application_output_missing")
            with Path(output).open("a") as stream:
                stream.write("partition_receipt=" + encoded + "\n")
            print("APPLICATION_PARTITION_VERIFIED " + encoded)
        else:
            raise PartitionRefused("application_arguments_refused")
        return 0
    except (PartitionRefused, ValueError, OSError, subprocess.SubprocessError):
        print("APPLICATION_PARTITION_REFUSED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
