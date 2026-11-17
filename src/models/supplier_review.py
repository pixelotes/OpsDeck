"""Structured supplier review questionnaires.

A ReviewTemplate holds an ordered list of ReviewQuestions. A supplier review is a
SecurityAssessment (the existing supplier review record, which compliance rules and
audits already use as evidence) that was filled in from a template: each answer is a
SupplierReviewAnswer that keeps a copy of the question text, so editing or deleting a
template never rewrites past reviews.

Question kinds:
* 'check'  - a yes/no question asked before the review (is the supplier still active?
  is it critical?). ``code`` lets the app act on the answer.
* 'review' - a point answered OK / Not OK / N/A, with a comment.
"""
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN
from src.utils.timezone_helper import now

KIND_CHECK = 'check'
KIND_REVIEW = 'review'
QUESTION_KINDS = (KIND_CHECK, KIND_REVIEW)

# Check questions the app acts on.
CODE_ACTIVE = 'supplier_active'
CODE_CRITICAL = 'supplier_critical'
CHECK_CODES = (CODE_ACTIVE, CODE_CRITICAL)

ANSWER_YES = 'yes'
ANSWER_NO = 'no'
ANSWER_OK = 'ok'
ANSWER_NOT_OK = 'not_ok'
ANSWER_NA = 'na'
CHECK_ANSWERS = (ANSWER_YES, ANSWER_NO)
REVIEW_ANSWERS = (ANSWER_OK, ANSWER_NOT_OK, ANSWER_NA)
ANSWER_LABELS = {
    ANSWER_YES: 'Yes', ANSWER_NO: 'No',
    ANSWER_OK: 'OK', ANSWER_NOT_OK: 'Not OK', ANSWER_NA: 'N/A',
}

# SecurityAssessment.status values used by questionnaire reviews.
STATUS_SCHEDULED = 'Scheduled'        # assigned to the owner, not filled in yet
STATUS_APPROVED = 'Approved'          # completed, every point OK or N/A
STATUS_ISSUES = 'Issues Found'        # completed, at least one point Not OK
STATUS_INACTIVE = 'Supplier Inactive'  # completed, the supplier is no longer used

DEFAULT_TEMPLATE_NAME = 'Supplier review'

# (kind, code, text, help_text)
DEFAULT_QUESTIONS = (
    (KIND_CHECK, CODE_ACTIVE, 'Is the supplier still active?',
     'Do we still use this supplier? If not, the review points can be skipped.'),
    (KIND_CHECK, CODE_CRITICAL, 'Is the supplier critical?',
     'Critical: losing it or a breach at it would seriously affect our services or data.'),
    (KIND_REVIEW, None, 'Issues with the supplier',
     'Incidents, poor service, disputes or complaints since the last review.'),
    (KIND_REVIEW, None, 'Certifications still held',
     'Certifications we rely on (ISO 27001, SOC 2…) are still valid.'),
    (KIND_REVIEW, None, 'Price increases',
     'Significant or unilateral price increases.'),
    (KIND_REVIEW, None, 'Changes to terms and conditions',
     'Changes to the contract, T&C, DPA or privacy terms.'),
    (KIND_REVIEW, None, 'Data breaches',
     'Security incidents or data breaches at the supplier.'),
    (KIND_REVIEW, None, 'SLAs met',
     'Agreed service levels have been met.'),
    (KIND_REVIEW, None, 'Other problems',
     'Anything else worth recording.'),
)


class ReviewTemplate(db.Model):
    __tablename__ = 'review_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())

    questions = db.relationship('ReviewQuestion', backref='template', lazy=True,
                                order_by='ReviewQuestion.position',
                                cascade=CASCADE_ALL_DELETE_ORPHAN)

    @property
    def check_questions(self):
        return [q for q in self.questions if q.kind == KIND_CHECK]

    @property
    def review_questions(self):
        return [q for q in self.questions if q.kind == KIND_REVIEW]


class ReviewQuestion(db.Model):
    __tablename__ = 'review_question'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('review_template.id'), nullable=False, index=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    kind = db.Column(db.String(20), default=KIND_REVIEW, nullable=False)
    code = db.Column(db.String(50))
    text = db.Column(db.String(255), nullable=False)
    help_text = db.Column(db.Text)


class SupplierReviewAnswer(db.Model):
    __tablename__ = 'supplier_review_answer'

    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('security_assessment.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('review_question.id', ondelete='SET NULL'), index=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    code = db.Column(db.String(50))
    question_text = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.String(20))
    comment = db.Column(db.Text)

    @property
    def answer_label(self):
        return ANSWER_LABELS.get(self.answer, '—')
