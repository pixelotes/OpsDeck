"""index_foreign_keys

Adds an index to every foreign key column that did not have one.

PostgreSQL indexes the referenced side of a foreign key, never the referencing side, so
these have to be declared. All 157 of them were used without one: a foreign key
column is by definition what a relationship traverses, and SQLAlchemy resolves
``parent.children`` as ``SELECT ... WHERE child.parent_id = ?``. The same applies to
deletes — the cascades in this app are ORM-level, so removing a parent issues one such
query per child collection.

67 of them sit on association tables, where the composite primary key covers the first
column and leaves the second uncovered: deleting a single Tag or User previously meant a
sequential scan of every association table referencing it.

The list was taken from pg_constraint rather than from the models, so columns already
covered by a composite index are not indexed twice. Tables belonging to the enterprise
plugin are left to their own models.

Revision ID: 022
Revises: 021
Create Date: 2026-08-06

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


# (table, column) — index name follows SQLAlchemy's convention, ix_<table>_<column>,
# so the models and the schema agree and drift detection stays quiet.
FOREIGN_KEYS = [
    ('activity', 'opportunity_id'),
    ('activity_execution', 'activity_id'),
    ('activity_execution', 'executor_id'),
    ('activity_execution_tags', 'tag_id'),
    ('activity_participants', 'user_id'),
    ('activity_related_object', 'activity_id'),
    ('activity_tags', 'tag_id'),
    ('asset_assignment', 'asset_id'),
    ('asset_assignment', 'user_id'),
    ('asset_history', 'asset_id'),
    ('asset_inventory', 'conducted_by_user_id'),
    ('asset_inventory_item', 'asset_id'),
    ('asset_inventory_item', 'inventory_id'),
    ('asset_inventory_item', 'user_id'),
    ('audit_control_item', 'audit_id'),
    ('audit_control_item', 'original_control_id'),
    ('audit_control_link', 'audit_item_id'),
    ('audit_evidence', 'offboarding_id'),
    ('audit_evidence', 'onboarding_id'),
    ('audit_participants', 'user_id'),
    ('bcdr_plan_assets', 'asset_id'),
    ('bcdr_plan_subscriptions', 'subscription_id'),
    ('bcdr_test_log', 'assignee_id'),
    ('bcdr_test_log', 'plan_id'),
    ('bcdr_test_tags', 'tag_id'),
    ('business_service', 'cost_center_id'),
    ('business_service', 'owner_id'),
    ('campaign', 'created_by_id'),
    ('campaign_groups', 'group_id'),
    ('campaign_tags', 'tag_id'),
    ('campaign_users', 'user_id'),
    ('candidate', 'stage_id'),
    ('catalog_risk', 'catalog_id'),
    ('catalog_risk', 'threat_type_id'),
    ('certificate_versions', 'certificate_id'),
    ('change_tags', 'tag_id'),
    ('compliance_audit', 'auditor_id'),
    ('compliance_audit', 'framework_id'),
    ('compliance_audit', 'internal_lead_id'),
    ('compliance_link', 'framework_control_id'),
    ('compliance_rule', 'framework_control_id'),
    ('configuration', 'asset_id'),
    ('configuration', 'license_id'),
    ('configuration', 'service_id'),
    ('configuration', 'software_id'),
    ('configuration_version', 'configuration_id'),
    ('configuration_version', 'created_by_id'),
    ('contact', 'supplier_id'),
    ('contract', 'supplier_id'),
    ('contract_item', 'contract_id'),
    ('control_mappings', 'target_control_id'),
    ('cost_history', 'subscription_id'),
    ('course_assignment', 'course_id'),
    ('course_assignment', 'user_id'),
    ('course_completion', 'assignment_id'),
    ('credentials', 'asset_id'),
    ('credentials', 'license_id'),
    ('custom_field_value', 'field_definition_id'),
    ('disposal_history', 'changed_by_id'),
    ('disposal_history', 'disposal_id'),
    ('documentation', 'software_id'),
    ('documentation_tags', 'tag_id'),
    ('event_rule', 'template_id'),
    ('framework_control', 'framework_id'),
    ('incident_assets', 'asset_id'),
    ('incident_subscriptions', 'subscription_id'),
    ('incident_suppliers', 'supplier_id'),
    ('incident_tags', 'tag_id'),
    ('incident_timeline_event', 'review_id'),
    ('incident_users', 'user_id'),
    ('lead', 'created_by_id'),
    ('link', 'software_id'),
    ('link_tags', 'tag_id'),
    ('maintenance_log', 'asset_id'),
    ('maintenance_log', 'assigned_to_id'),
    ('maintenance_log', 'peripheral_id'),
    ('maintenance_log_tags', 'tag_id'),
    ('notification_event', 'template_id'),
    ('offboarding_process', 'manager_id'),
    ('offboarding_process', 'user_id'),
    ('onboarding_process', 'assigned_buddy_id'),
    ('onboarding_process', 'assigned_manager_id'),
    ('onboarding_process', 'pack_id'),
    ('onboarding_process', 'user_id'),
    ('opportunity', 'budget_id'),
    ('opportunity', 'primary_contact_id'),
    ('opportunity', 'requirement_id'),
    ('opportunity', 'risk_id'),
    ('opportunity', 'supplier_id'),
    ('opportunity_task', 'opportunity_id'),
    ('org_chart_snapshot', 'created_by_id'),
    ('pack_communication', 'pack_id'),
    ('pack_communication', 'template_id'),
    ('pack_item', 'course_id'),
    ('pack_item', 'pack_id'),
    ('pack_item', 'service_id'),
    ('pack_item', 'software_id'),
    ('pack_item', 'subscription_id'),
    ('payment_method', 'user_id'),
    ('peripheral_assignment', 'peripheral_id'),
    ('peripheral_assignment', 'user_id'),
    ('permission', 'group_id'),
    ('permission', 'user_id'),
    ('policy_acknowledgement', 'policy_version_id'),
    ('policy_acknowledgement', 'user_id'),
    ('policy_version', 'policy_id'),
    ('policy_version_groups', 'group_id'),
    ('policy_version_users', 'user_id'),
    ('post_incident_review', 'locked_by_id'),
    ('process_item', 'offboarding_process_id'),
    ('process_item', 'onboarding_process_id'),
    ('purchase_cost_history', 'purchase_id'),
    ('purchase_cost_history', 'user_id'),
    ('purchase_tags', 'tag_id'),
    ('purchase_users', 'user_id'),
    ('request_tags', 'tag_id'),
    ('requirement_action', 'created_by_id'),
    ('requirement_action', 'requirement_id'),
    ('risk', 'source_catalog_risk_id'),
    ('risk', 'threat_type_id'),
    ('risk_affected_item', 'risk_id'),
    ('risk_assessment_changes', 'change_id'),
    ('risk_assessment_evidence', 'attachment_id'),
    ('risk_assessment_evidence', 'item_id'),
    ('risk_assessment_item', 'assessment_id'),
    ('risk_assessment_item', 'original_risk_id'),
    ('risk_category', 'risk_id'),
    ('risk_history', 'risk_id'),
    ('risk_history', 'user_id'),
    ('risk_mitigation_activities', 'activity_id'),
    ('risk_reference', 'risk_id'),
    ('roadmap', 'owner_id'),
    ('roadmap_goal', 'owner_id'),
    ('roadmap_initiative', 'owner_id'),
    ('scheduled_communication', 'audit_log_id'),
    ('scheduled_communication', 'event_rule_id'),
    ('scheduled_communication', 'recipient_user_id'),
    ('scheduled_communication', 'template_id'),
    ('security_assessment', 'supplier_id'),
    ('service_activities', 'activity_id'),
    ('service_certificates', 'certificate_id'),
    ('service_component', 'service_id'),
    ('service_credentials', 'credential_id'),
    ('service_dependencies', 'child_id'),
    ('service_documentation', 'documentation_id'),
    ('service_policies', 'policy_id'),
    ('service_users', 'user_id'),
    ('software', 'supplier_id'),
    ('subscription_contacts', 'contact_id'),
    ('subscription_payment_methods', 'payment_method_id'),
    ('subscription_tags', 'tag_id'),
    ('subscription_users', 'user_id'),
    ('uar_execution', 'comparison_id'),
    ('uar_finding', 'assigned_to_id'),
    ('uar_finding', 'execution_id'),
    ('uar_finding', 'security_incident_id'),
    ('user_groups', 'group_id'),
]


def upgrade():
    for table, column in FOREIGN_KEYS:
        op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    for table, column in reversed(FOREIGN_KEYS):
        op.drop_index(f'ix_{table}_{column}', table_name=table)
