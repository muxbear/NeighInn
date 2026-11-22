"""统一领域模型汇总（re-export barrel）。新增模型文件必须在此导入，否则 Alembic 与 create_all 不会感知。"""

# ruff: noqa: F401

from src.db.models.common import Entity
from src.db.models.community import Community, Region
from src.db.models.content import (
    Broadcast,
    HelpRequest,
    HelpResponse,
    ItemComment,
    LifeComment,
    LifePost,
    Report,
)
from src.db.models.engagement import Favorite, HotKeyword, SearchHistory, ViewHistory
from src.db.models.funds import (
    FinanceAdjustment,
    LedgerEntry,
    PaymentTransaction,
    Reconciliation,
    WalletAccount,
    Withdrawal,
)
from src.db.models.governance import (
    Dispute,
    DisputeEvidence,
    DisputeMessage,
    Feedback,
    RepairOrder,
)
from src.db.models.identity import (
    Certification,
    CreditLog,
    PlatformUser,
    Resident,
    User,
    UserPenalty,
)
from src.db.models.marketplace import Item, ItemAudit, ItemCategory, ItemMedia
from src.db.models.notification import (
    AppNotification,
    Notice,
    NoticeRead,
    NotificationRecord,
    NotificationTask,
    NotificationTemplate,
)
from src.db.models.social import (
    Conversation,
    Friend,
    FriendBlock,
    FriendRemark,
    FriendRequest,
    Message,
)
from src.db.models.system import (
    AdminUser,
    AdminUserRegionGrant,
    AuditLog,
    Dictionary,
    DictionaryItem,
    ExportJob,
    FileObject,
    IdempotencyKey,
    OutboxEvent,
    ParameterItem,
    ParameterKey,
    Permission,
    ProcessedEvent,
    Role,
    admin_user_communities,
    admin_user_roles,
    role_permissions,
)
from src.db.models.trade import Order, OrderEvent, Review

__all__ = [name for name in dir() if not name.startswith("_")]
