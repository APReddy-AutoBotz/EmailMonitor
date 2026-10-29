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
# Existing SQL cases moved using observed phase timings; the join still requires each case.
MEASURED_SQL = (
    (
        "services/backend/tests/test_association_tenant.py::test_real_relational_rec"
        "eipts_replay_preserves_review_and_no_contact"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[owner-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[admin-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[data_steward-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[reviewer-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[operator-False]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_review_role_ma"
        "trix_api_and_csrf[viewer-False]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_cross_tenant_p"
        "ool_rls_and_catalog_permissions"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_correction_his"
        "tory_and_citations_no_free_address"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_cancel_preserv"
        "es_permitted_receipts_but_fences_new_ingestion"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_current_source"
        "_lifecycle_membership_denials[revoke]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_current_source"
        "_lifecycle_membership_denials[expire]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_current_source"
        "_lifecycle_membership_denials[offboard]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_current_source"
        "_lifecycle_membership_denials[membership]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_concurrent_rev"
        "iews_one_revision_and_one_atomic_receipt"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_production_can"
        "not_read_or_review_synthetic_associations"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_ordinary_opera"
        "tor_derives_with_no_catalog_or_receipt_update_grant"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_new_policy_ver"
        "sion_invalidates_old_receipt_without_implicit_reapproval"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_source_disable"
        "_and_clock_expired_session_refuse_current_read"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_atomic_derivat"
        "ion_and_review_rollback"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[owner-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[admin-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[data_steward-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[reviewer-True]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[operator-False]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_preserv"
        "es_existing_review_role_matrix[viewer-False]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_databas"
        "e_entrypoint_refuses_invalid_input[author]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_databas"
        "e_entrypoint_refuses_invalid_input[evidence]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_unlink_databas"
        "e_entrypoint_refuses_invalid_input[stale]"
    ),
    (
        "services/backend/tests/test_association_tenant.py::test_real_concurrent_unl"
        "inks_have_one_revision_and_audit_receipt"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "cross_job_paper_pages_reviews_and_exact_item_intersection"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_preview_immutable_snapshot_and_key_conflict[csv]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_preview_immutable_snapshot_and_key_conflict[xlsx]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[claim_finish-deletion]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[claim_finish-retention]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[claim_finish-session]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[claim_finish-source]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[ready_download-deletion]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[ready_download-retention]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[ready_download-session]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_exports_keep_current_authority[ready_download-source]"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "paper_api_tenant_and_private_helper_boundaries"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "observed_identity_requires_consistent_evidenced_facts"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "concurrent_jobs_keep_distinct_observations_and_stale_work_refuses"
    ),
    (
        "services/backend/tests/test_retained_paper_identity_tenant.py::test_actual_"
        "same_doi_in_two_tenants_has_no_shared_rows_or_visibility"
    ),
)
RESERVED_SQL = (
    *RETAINED_SQL,
    *PDF_ACCEPTANCE,
    *SERVICE_SQL,
    *TIMING_SQL,
    *MEASURED_SQL,
)
# Measured real-CI cases moved to the third identical guarded SQL runner.
CAPACITY_EXTRA = (
    (
        "services/backend/tests/test_service_reuse_broker.py::test_reused_observatio"
        "n_survives_worker_crash_and_original_redelivery[html]"
    ),
    (
        "services/backend/tests/test_service_reuse_broker.py::test_reused_observatio"
        "n_survives_worker_crash_and_original_redelivery[pdf]"
    ),
    (
        "services/backend/tests/test_service_reuse_broker.py::test_reused_observatio"
        "n_survives_worker_crash_and_original_redelivery[article_xml]"
    ),
    (
        "services/backend/tests/test_service_reuse_broker.py::test_reused_observatio"
        "n_survives_worker_crash_and_original_redelivery[provider]"
    ),
    (
        "services/backend/tests/test_service_reuse_tenant.py::test_service_worker_re"
        "ads_only_its_target_and_never_acquires_fresh_bytes[html]"
    ),
    (
        "services/backend/tests/test_service_reuse_tenant.py::test_service_worker_re"
        "ads_only_its_target_and_never_acquires_fresh_bytes[pdf]"
    ),
    (
        "services/backend/tests/test_service_reuse_tenant.py::test_service_worker_re"
        "ads_only_its_target_and_never_acquires_fresh_bytes[article_xml]"
    ),
    (
        "services/backend/tests/test_service_reuse_tenant.py::test_service_worker_re"
        "ads_only_its_target_and_never_acquires_fresh_bytes[provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_non_html"
        "_copy_keeps_original_binding_and_replays[pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_non_html"
        "_copy_keeps_original_binding_and_replays[article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_non_html"
        "_copy_keeps_original_binding_and_replays[provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_source_fence_s"
        "erializes_item_read_with_deletion[pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_source_fence_s"
        "erializes_item_read_with_deletion[article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_source_fence_s"
        "erializes_item_read_with_deletion[provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[revoked_policy-pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[revoked_policy-article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[revoked_policy-provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[retention-pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[retention-article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[retention-provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[suppression-pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[suppression-article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[suppression-provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[deleted-pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[deleted-article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[deleted-provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[expired-pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[expired-article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_source_a"
        "uthority_changes_refuse_before_copy[expired-provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_re"
        "spects_user_cutoff[pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_re"
        "spects_user_cutoff[article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_re"
        "spects_user_cutoff[provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_ne"
        "ver_resolves_foreign_tenant_batch[pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_ne"
        "ver_resolves_foreign_tenant_batch[article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_bound_reuse_ne"
        "ver_resolves_foreign_tenant_batch[provider]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_public_bound_r"
        "euse_review_export_and_source_deletion[pdf]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_public_bound_r"
        "euse_review_export_and_source_deletion[article_xml]"
    ),
    (
        "services/backend/tests/test_staged_reuse_sql_tenant.py::test_public_bound_r"
        "euse_review_export_and_source_deletion[provider]"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_real_api_tenant_sele"
        "ction_and_pool_reuse"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_sql_rls_blocks_forge"
        "d_tenant_and_contextless_writes"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_roles_cannot_manage_"
        "members[operator]"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_roles_cannot_manage_"
        "members[reviewer]"
    ),
    ("services/backend/tests/test_tenant_foundation.py::test_roles_cannot_manage_members[viewer]"),
    (
        "services/backend/tests/test_tenant_foundation.py::test_roles_cannot_manage_"
        "members[data_steward]"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_owner_transfer_guard"
        "_and_atomic_transfer"
    ),
    ("services/backend/tests/test_tenant_foundation.py::test_admin_cannot_assign_or_change_owner"),
    (
        "services/backend/tests/test_tenant_foundation.py::test_revocation_stale_ses"
        "sion_csrf_and_revision"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_lifecycle_suspension"
        "_recovery_and_terminal_state"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_expired_revoked_and_"
        "fabricated_session"
    ),
    ("services/backend/tests/test_tenant_foundation.py::test_runtime_rejects_owner_connection"),
    ("services/backend/tests/test_tenant_foundation.py::test_force_rls_and_composite_keys"),
    (
        "services/backend/tests/test_tenant_foundation.py::test_oidc_browser_binding"
        "_and_callback_replay"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_test_provider_cannot"
        "_activate_in_production"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_registered_membershi"
        "p_addition_is_tenant_scoped"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_concurrent_last_owne"
        "r_removal_is_serialized"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_database_runtime_is_"
        "direct_login_and_revision_body_is_strict"
    ),
    (
        "services/backend/tests/test_tenant_foundation.py::test_authentication_and_r"
        "untime_privileges_are_separate"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_upgrade_"
        "crash_replay_one_effect_current_revision"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_optout_o"
        "r_uncomposed_remains_truthful[False-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_optout_o"
        "r_uncomposed_remains_truthful[True-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_missing_"
        "browser_policy_keeps_static_without_effect"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[token-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[token-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[generation-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[generation-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[pause-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[pause-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[cancel-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[cancel-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[policy-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[policy-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[deletion-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[deletion-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[expiry-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[expiry-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[tenant-False]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_current_"
        "fences_before_dispatch_and_before_commit[lease_deletion_generation-True]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_stale_di"
        "scovery_revision_refused"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_browser_"
        "provenance_failure_keeps_static_and_no_effect"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_callback"
        "_cancel_blocks_derive_and_replay"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_retained"
        "_browser_expiry_refuses_recovery_without_dispatch[contact_deadline]"
    ),
    (
        "services/backend/tests/test_tooltip_execution_tenant.py::test_real_retained"
        "_browser_expiry_refuses_recovery_without_dispatch[excerpt_deadline]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_running_job_admi"
        "ssion_and_one_settlement_each"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_two_tenant_round"
        "_robin_under_shared_pool_contention"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_quota_reduction_"
        "stops_remaining_units_without_recharging"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_active_reservati"
        "on_survives_temporary_full_quota_and_cancel_releases"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_export_reduction"
        "_hides_download_and_keeps_private_artifact"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_current_export_d"
        "isable_closes_claim_and_reconciliation"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_attempt_s"
        "pacing_backoff_and_idempotent_admission"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_current_network_"
        "entitlement_refusal_does_not_count_attempt"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_captured_job_lim"
        "its_do_not_expand_on_upgrade"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_concurrent_claim"
        "s_never_oversubscribe_tenant_or_recharge"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_contended_source"
        "_grant_and_backoff_use_post_lock_time"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[expired]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[cleanup_finished]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[failure_finished]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[response_finished]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[wrong_nonce]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_source_success_r"
        "equires_its_live_active_current_lease[waiting]"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_draft_parse_cann"
        "ot_commit_after_lease_expiry_and_slot_reuse"
    ),
    (
        "services/backend/tests/test_admission_tenant.py::test_real_discovery_only_p"
        "olicy_admits_fixture_io_without_contact_extraction"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_unknown_total_act"
        "ual_counters_partial_dynamic_and_replay"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_all_no_contact_co"
        "mpletes_without_accepted_contacts"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_cap_partial_never"
        "_claims_known_denominator"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_pause_generation_"
        "resume_checkpoint_old_lease_denied"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_cancel_retains_pe"
        "rmitted_source_but_fences_uncommitted_effect"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_exhausted_last_at"
        "tempt_pause_settles_and_retry_is_new_lineage"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_started_writes_ne"
        "ed_current_lease_and_runtime_tables_are_read_only"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_revision_conflict"
        "_does_not_start_or_reopen_terminal"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_mixed_exhausted_a"
        "nd_running_job_does_not_terminalize_live_work"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_atomic_review_eve"
        "nt_is_metadata_only_and_replayed_after_completion"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_page_committed_be"
        "fore_effect_pause_resumes_without_refetch"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_catalog_guard_pre"
        "serves_live_work_and_item_scope"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_identifier_api_cs"
        "rf_and_authorized_sse_replay"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_stream_rechecks_s"
        "ource_before_each_cached_frame"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_failed_pagination"
        "_retry_inherits_committed_articles_without_new_effects"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_review_rejection_"
        "does_not_turn_processing_into_failure"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_source_ceiling_is"
        "_partial_and_not_a_false_percentage"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_reconciliation_re"
        "opens_confirmed_unleased_pending_only"
    ),
    (
        "services/backend/tests/test_progress_tenant.py::test_real_cancel_after_page"
        "_checkpoint_terminalizes_frontier_and_reconcile_is_inert"
    ),
)
CAPACITY_SQL = (*MEASURED_SQL, *CAPACITY_EXTRA)
PROFILES = ("backend", "outcome_sql", "capacity_sql")
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
COMMON = ("source_tree", "config", "full", *PROFILES, *("excluded_" + p for p in PROFILES))


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
    if len(set(CAPACITY_SQL)) != len(CAPACITY_SQL) or any(full[node] != 1 for node in CAPACITY_SQL):
        raise PartitionRefused("application_collection_refused")
    capacity = set(CAPACITY_SQL)
    reserved = set(RESERVED_SQL)
    result = {
        "backend": [node for node in nodes if node not in reserved and node not in capacity],
        "outcome_sql": [node for node in nodes if node in reserved and node not in capacity],
        "capacity_sql": [node for node in nodes if node in capacity],
    }
    counts = [Counter(result[key]) for key in PROFILES]
    if (
        any(not count for count in counts)
        or any(counts[i] & counts[j] for i in range(len(counts)) for j in range(i + 1, len(counts)))
        or sum(counts, Counter()) != full
    ):
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
            or Counter(self.deselected) != Counter(self.excluded)
            or Counter(self.discovered) != Counter(self.full)
        ):
            raise PartitionRefused("application_selection_changed")
        self.collection_complete = True

    @property
    def excluded(self) -> list[str]:
        return [
            node
            for profile in PROFILES
            if profile != self.profile
            for node in self.assigned[profile]
        ]

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
            **{
                "excluded_" + profile: manifest(
                    [
                        node
                        for other in PROFILES
                        if other != profile
                        for node in self.assigned[other]
                    ]
                )
                for profile in PROFILES
            },
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
    if profile in {"backend", "capacity_sql"}:
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
    for key in ("full", *PROFILES, *("excluded_" + p for p in PROFILES), "executed", "deselected"):
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
    outcome_expected = [node for node in RESERVED_SQL if node not in CAPACITY_SQL]
    if (
        value["outcome_sql"] != manifest(outcome_expected)
        or value["capacity_sql"] != manifest(CAPACITY_SQL)
        or value["excluded_backend"] != manifest((*RESERVED_SQL, *CAPACITY_EXTRA))
        or value["full"]["count"] != sum(value[p]["count"] for p in PROFILES)
        or any(
            value["excluded_" + p]["count"] != value["full"]["count"] - value[p]["count"]
            for p in PROFILES
        )
        or value["executed"] != value[profile]
        or value["deselected"] != value["excluded_" + profile]
    ):
        raise PartitionRefused("application_receipt_refused")
    return value


def join(environment: Mapping[str, str]) -> None:
    if any(
        environment.get(key) != "success"
        for key in ("BACKEND_RESULT", "OUTCOME_SQL_RESULT", "CAPACITY_SQL_RESULT", "STATIC_RESULT")
    ):
        raise PartitionRefused("application_dependency_failed")
    receipts = [
        decode_receipt(environment.get(profile.upper() + "_RECEIPT", ""), profile)
        for profile in PROFILES
    ]
    if (
        any(any(receipt[key] != receipts[0][key] for key in COMMON) for receipt in receipts[1:])
        or receipts[0]["source_tree"] != source_tree()
        or receipts[0]["config"] != configuration()
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
