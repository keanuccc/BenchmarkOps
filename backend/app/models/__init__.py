"""ORM model registry.

Importing this package must import every model module so SQLAlchemy's
Base.metadata is fully populated before create_all / migrations run.

Stage 1+ sub-agents add their model imports here.
"""
from app.models.base import Base  # noqa: F401
from app.models.audit import AuditEvent  # noqa: F401

# Aggregate models (registered on Base.metadata via import side-effect).
from app.models.project import Project  # noqa: F401
from app.models.model import Model  # noqa: F401
from app.models.dataset import Dataset, DatasetRow, DatasetVersion  # noqa: F401
from app.models.prompt import Prompt  # noqa: F401
from app.models.benchmark import Benchmark  # noqa: F401
from app.models.experiment import Experiment, ExperimentResult  # noqa: F401
from app.models.import_job import ImportJob  # noqa: F401
from app.models.report import Report  # noqa: F401
from app.models.task import EvaluationTask  # noqa: F401
from app.models.organization import ApiKey, Organization  # noqa: F401
from app.models.scheduled_report import ScheduledReport  # noqa: F401
from app.models.webhook import WebhookSubscription  # noqa: F401

__all__ = [
    "Base",
    "AuditEvent",
    "Project",
    "Model",
    "Dataset",
    "DatasetRow",
    "DatasetVersion",
    "Prompt",
    "Benchmark",
    "Experiment",
    "ExperimentResult",
    "ImportJob",
    "Report",
    "EvaluationTask",
    "Organization",
    "ApiKey",
    "ScheduledReport",
    "WebhookSubscription",
]
