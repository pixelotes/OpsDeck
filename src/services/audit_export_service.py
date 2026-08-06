"""
Service for exporting ComplianceAudit defense packs.

Generates a ZIP file containing:
- Main report document (PDF)
- Evidence documents organized by control
- All attachments
- External links manifest
"""
import os
import tempfile
import shutil
import json
from flask import render_template, current_app
from ..models import db
from ..models.audits import ComplianceAudit
from src.utils.timezone_helper import now


class AuditPackExporter:
    """
    Main service for exporting audit defense packs.
    """

    # All supported evidence types
    EVIDENCE_TYPES = {
        # Manual Evidence Types (structural)
        'OrgChartSnapshot': 'org_chart',
        'Asset': 'asset',
        'Peripheral': 'peripheral',
        'Software': 'software',
        'License': 'license',
        'Supplier': 'supplier',
        'Purchase': 'purchase',
        'Budget': 'budget',
        'Subscription': 'subscription',
        'Link': 'link',
        'Documentation': 'documentation',
        'Policy': 'policy',
        'Course': 'course',
        'BCDRPlan': 'bcdr_plan',
        'SecurityIncident': 'security_incident',
        'Risk': 'risk',
        'RiskAssessment': 'risk_assessment',
        'AssetInventory': 'asset_inventory',
        'BusinessService': 'business_service',
        'Onboarding': 'onboarding',
        'Offboarding': 'offboarding',
        'Contract': 'contract',
        'Change': 'change',

        # Automated Evidence Types
        'MaintenanceLog': 'maintenance_log',
        'BCDRTestLog': 'bcdr_test_log',
        'SecurityAssessment': 'security_assessment',
        'ActivityExecution': 'activity_execution',
        'SecurityActivity': 'security_activity',
        'Campaign': 'campaign',
    }

    def __init__(self, audit_id):
        """
        Initialize exporter for a specific audit.

        Args:
            audit_id: ID of the ComplianceAudit to export
        """
        self.audit = db.get_or_404(ComplianceAudit, audit_id)
        self.temp_dir = None
        self.evidence_dir = None
        self.attachments_dir = None
        self.external_links = []
        self.stats = {
            'controls': 0,
            'evidence_items': 0,
            'attachments': 0,
            'external_links': 0,
            'mini_pdfs': 0
        }

    def export(self):
        """
        Main export function. Generates complete defense pack.

        Returns:
            tuple: (zip_path, stats_dict)
        """
        try:
            # 1. Setup temporary directory structure
            self._setup_directories()

            # 2. Generate main report document
            self._generate_main_report()

            # 3. Process all audit items and their evidence
            self._process_audit_items()

            # 4. Generate manifest
            self._generate_manifest()

            # 5. Create ZIP file
            zip_path = self._create_zip()

            return zip_path, self.stats

        finally:
            # Cleanup temp directory (caller is responsible for zip file)
            if self.temp_dir and os.path.exists(self.temp_dir):
                # Don't delete yet - zip file is inside
                pass

    def _setup_directories(self):
        """Create temporary directory structure."""
        self.temp_dir = tempfile.mkdtemp(prefix='audit_export_')
        self.evidence_dir = os.path.join(self.temp_dir, 'evidence')
        self.attachments_dir = os.path.join(self.temp_dir, 'attachments')

        os.makedirs(self.evidence_dir, exist_ok=True)
        os.makedirs(self.attachments_dir, exist_ok=True)

    def _generate_main_report(self):
        """
        Generate the main defense pack report document.

        This is the high-level summary document with:
        - Audit metadata
        - SOA table
        - Control status summary
        - Evidence summary
        """
        # Collect statistics
        items = list(self.audit.audit_items.all())
        self.stats['controls'] = len(items)

        status_counts = {}
        for item in items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1

        # Render HTML
        html_content = render_template(
            'export/main_report.html',
            audit=self.audit,
            items=items,
            status_counts=status_counts,
            generated_at=now()
        )

        # Save as both HTML and PDF
        # HTML version for reference
        html_path = os.path.join(self.temp_dir, 'Defense_Pack_Report.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # PDF version (primary document)
        try:
            from weasyprint import HTML
            pdf_path = os.path.join(self.temp_dir, 'Defense_Pack_Report.pdf')
            HTML(string=html_content).write_pdf(pdf_path)
        except ImportError:
            current_app.logger.warning("WeasyPrint not available, skipping PDF generation for main report")
        except Exception as e:
            current_app.logger.error(f"Error generating PDF for main report: {e}")

    def _process_audit_items(self):
        """Process all audit control items and their evidence."""
        for item in self.audit.audit_items:
            self._process_control_item(item)

    def _process_control_item(self, item):
        """
        Process a single control item and all its linked evidence.

        Args:
            item: AuditControlItem instance
        """
        # Create control directory
        control_slug = item.control_code.replace('.', '_')
        control_dir = os.path.join(self.evidence_dir, control_slug)
        os.makedirs(control_dir, exist_ok=True)

        # Create control attachments subdirectory
        control_attachments_dir = os.path.join(control_dir, 'attachments')
        os.makedirs(control_attachments_dir, exist_ok=True)

        # Process control-level attachments
        for attachment in item.attachments:
            self._copy_attachment(attachment, control_attachments_dir)

        # Process each evidence link
        for link in item.linked_objects:
            self._process_evidence_link(link, control_dir, control_attachments_dir)

    def _process_evidence_link(self, link, control_dir, attachments_dir):
        """
        Process a single evidence link.

        Args:
            link: AuditControlLink instance
            control_dir: Directory for this control's evidence
            attachments_dir: Directory for attachments
        """
        obj = link.linked_object

        # Handle orphaned links
        if not obj:
            self._log_orphaned_link(link, control_dir)
            return

        self.stats['evidence_items'] += 1

        # Get evidence type template key
        evidence_type = link.linkable_type
        template_key = self.EVIDENCE_TYPES.get(evidence_type, 'generic')

        # Render evidence HTML
        html_content = self._render_evidence_html(link, obj, template_key)

        # Save as both HTML and PDF
        # HTML version for reference
        html_filename = f"{evidence_type}_{link.linkable_id}.html"
        html_filepath = os.path.join(control_dir, html_filename)
        with open(html_filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # PDF version (primary document for auditors)
        try:
            from weasyprint import HTML
            pdf_filename = f"{evidence_type}_{link.linkable_id}.pdf"
            pdf_filepath = os.path.join(control_dir, pdf_filename)
            HTML(string=html_content).write_pdf(pdf_filepath)
            self.stats['mini_pdfs'] += 1
        except ImportError:
            # WeasyPrint not available, keep HTML only
            self.stats['mini_pdfs'] += 1
        except Exception as e:
            current_app.logger.warning(f"Error generating PDF for {evidence_type}_{link.linkable_id}: {e}")
            self.stats['mini_pdfs'] += 1

        # Copy attachments if evidence has any
        if hasattr(obj, 'attachments'):
            for attachment in obj.attachments:
                self._copy_attachment(attachment, attachments_dir)

        # Handle special cases
        if evidence_type == 'Link' and hasattr(obj, 'url'):
            self._add_external_link(link, obj.url, obj.title if hasattr(obj, 'title') else obj.name)

        if evidence_type == 'Documentation' and hasattr(obj, 'url') and obj.url:
            self._add_external_link(link, obj.url, obj.title if hasattr(obj, 'title') else obj.name)

    def _render_evidence_html(self, link, obj, template_key):
        """
        Render evidence object as HTML.

        Args:
            link: AuditControlLink instance
            obj: The linked object (evidence)
            template_key: Template identifier

        Returns:
            str: Rendered HTML content
        """
        template_name = f'export/evidence/{template_key}.html'

        # Check if template exists, fallback to generic
        try:
            return render_template(
                template_name,
                evidence=obj,
                link=link,
                audit=self.audit,
                generated_at=now()
            )
        except Exception:
            # Fallback to generic template
            return render_template(
                'export/evidence/generic.html',
                evidence=obj,
                link=link,
                audit=self.audit,
                generated_at=now()
            )

    def _copy_attachment(self, attachment, target_dir):
        """
        Copy an attachment file to the export directory.

        Args:
            attachment: Attachment model instance
            target_dir: Target directory path
        """
        if not attachment.file_path or not os.path.exists(attachment.file_path):
            return

        try:
            target_path = os.path.join(target_dir, attachment.filename)

            # Avoid duplicate filenames
            if os.path.exists(target_path):
                base, ext = os.path.splitext(attachment.filename)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
                    counter += 1

            shutil.copy2(attachment.file_path, target_path)
            self.stats['attachments'] += 1

        except Exception as e:
            # Log error but don't fail the export
            current_app.logger.error(f"Failed to copy attachment {attachment.id}: {e}")

    def _add_external_link(self, link, url, title):
        """
        Add an external link to the manifest.

        Args:
            link: AuditControlLink instance
            url: External URL
            title: Link title/name
        """
        self.external_links.append({
            'control': link.audit_item.control_code,
            'title': title,
            'url': url,
            'evidence_type': link.linkable_type,
            'is_automated': link.is_automated
        })
        self.stats['external_links'] += 1

    def _log_orphaned_link(self, link, control_dir):
        """
        Log an orphaned evidence link.

        Args:
            link: AuditControlLink instance with missing target
            control_dir: Control directory path
        """
        orphan_log = os.path.join(control_dir, '_orphaned_evidence.txt')

        with open(orphan_log, 'a', encoding='utf-8') as f:
            f.write("Orphaned Evidence:\n")
            f.write(f"  Type: {link.linkable_type}\n")
            f.write(f"  ID: {link.linkable_id}\n")
            f.write(f"  Description: {link.description or 'N/A'}\n")
            f.write(f"  Automated: {link.is_automated}\n\n")

    def _generate_manifest(self):
        """Generate export manifest with metadata and external links."""
        manifest = {
            'audit': {
                'id': self.audit.id,
                'name': self.audit.name,
                'framework': self.audit.framework.name if self.audit.framework else None,
                'status': self.audit.status,
                'outcome': self.audit.outcome,
                'start_date': self.audit.start_date.isoformat() if self.audit.start_date else None,
                'end_date': self.audit.end_date.isoformat() if self.audit.end_date else None,
                'internal_lead': self.audit.internal_lead.name if self.audit.internal_lead else None,
                'auditor': self.audit.auditor.name if self.audit.auditor else None,
            },
            'export': {
                'generated_at': now().isoformat(),
                'generated_by': 'OpsDeck Audit Export Service',
                'version': '1.0'
            },
            'statistics': self.stats,
            'external_links': self.external_links
        }

        # Save external links as separate file for easy access
        if self.external_links:
            links_file = os.path.join(self.temp_dir, 'external_links.txt')
            with open(links_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("EXTERNAL LINKS REFERENCED IN THIS AUDIT\n")
                f.write("=" * 80 + "\n\n")

                for ext_link in self.external_links:
                    f.write(f"Control: {ext_link['control']}\n")
                    f.write(f"Title: {ext_link['title']}\n")
                    f.write(f"URL: {ext_link['url']}\n")
                    f.write(f"Type: {ext_link['evidence_type']}")
                    if ext_link['is_automated']:
                        f.write(" (Automated)")
                    f.write("\n\n" + "-" * 80 + "\n\n")

        # Save JSON manifest
        manifest_path = os.path.join(self.temp_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    def _create_zip(self):
        """
        Create ZIP file from temporary directory.

        Returns:
            str: Path to created ZIP file
        """
        # Generate ZIP filename
        audit_name_slug = self.audit.name.replace(' ', '_').replace('/', '_')
        timestamp = now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"audit_{self.audit.id}_{audit_name_slug}_{timestamp}"

        # Create ZIP in temp directory's parent (so we can delete temp_dir after)
        zip_base_path = os.path.join(os.path.dirname(self.temp_dir), zip_filename)

        # Create the archive
        shutil.make_archive(zip_base_path, 'zip', self.temp_dir)

        return f"{zip_base_path}.zip"


def export_audit_pack(audit_id):
    """
    Convenience function to export an audit pack.

    Args:
        audit_id: ID of the ComplianceAudit to export

    Returns:
        tuple: (zip_path, stats_dict)
    """
    exporter = AuditPackExporter(audit_id)
    return exporter.export()
