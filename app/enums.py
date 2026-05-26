from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    CLIENT = "client"
    AGENT = "agent"
    MANAGER = "manager"
    ADMIN = "admin"


class LeadType(StrEnum):
    CONSULTATION = "consultation"
    QUESTION = "question"
    AGENT_CLIENT = "agent_client"


class LeadStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"
    CANCELED = "canceled"


class BonusStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELED = "canceled"


class ChatStatus(StrEnum):
    OPEN = "open"
    ACTIVE = "active"
    CLOSED = "closed"
