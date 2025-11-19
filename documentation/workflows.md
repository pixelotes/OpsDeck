# Workflows

OpsDeck is designed around several key operational workflows.

## Asset Lifecycle Management

1.  **Procurement**:
    *   A **Purchase** is recorded, linked to a **Supplier** and **Budget**.
    *   The purchase details (cost, date, warranty) form the basis for the asset record.

2.  **Onboarding**:
    *   An **Asset** is created from the purchase.
    *   Status is set to "In Stock".
    *   Asset is tagged and assigned a location.

3.  **Assignment**:
    *   The asset is assigned to a **User**.
    *   Status changes to "In Use".
    *   The user sees the asset in their profile.

4.  **Maintenance**:
    *   Issues are logged via **MaintenanceLog**.
    *   Status may change to "In Repair".
    *   Costs of repair are tracked.

5.  **End of Life**:
    *   Asset is marked as "Awaiting Disposal".
    *   A **DisposalRecord** is created, detailing the method (e-waste, sale, donation) and any proceeds.
    *   Asset is archived but remains in history for audit purposes.

## Compliance & GRC

1.  **Framework Definition**:
    *   **Frameworks** (e.g., ISO 27001) are imported or created.
    *   **FrameworkControls** (e.g., A.5.1) are defined.

2.  **Linking (Evidence Collection)**:
    *   Users navigate to any object (Asset, Policy, Supplier, etc.).
    *   Using the "Compliance Links" component, they link the object to a specific control.
    *   A justification/description is provided (e.g., "This firewall asset satisfies control A.13.1").

3.  **Auditing**:
    *   Auditors view the Framework page to see all controls.
    *   Drilling down into a control reveals all linked evidence (Assets, Policies, etc.).
    *   Gaps (controls with no links) are easily identified.

## Incident Management

1.  **Reporting**:
    *   A **SecurityIncident** is logged (title, severity, description).
    *   Status starts as "Open".

2.  **Investigation**:
    *   Evidence is gathered and attached.
    *   Affected assets or users are linked.

3.  **Resolution**:
    *   Root cause is identified.
    *   Status changes to "Resolved".

4.  **Review**:
    *   A Post-Incident Review (PIR) is conducted.
    *   Lessons learned are documented.
    *   Status changes to "Closed".

## Procurement & Budgets

1.  **Budgeting**:
    *   **Budgets** are defined for the fiscal year (e.g., "Hardware 2024").

2.  **Purchasing**:
    *   **Purchases** are logged and deducted from the selected budget.
    *   **Subscriptions** are set up for recurring costs.

3.  **Forecasting**:
    *   The dashboard provides a 12-month forecast based on active subscriptions and renewal dates.
    *   Spend analysis reports show spending by category and supplier.
