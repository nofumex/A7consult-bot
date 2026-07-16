from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_users_platform_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), default="telegram", index=True, nullable=False)
    platform_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    username: Mapped[str | None] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_client: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    admin_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    amo_agent_lead_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    amo_agent_contact_id: Mapped[int | None] = mapped_column(BigInteger)
    amo_agent_status_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    amo_agent_sync_status: Mapped[str | None] = mapped_column(String(32))
    amo_agent_sync_error: Mapped[str | None] = mapped_column(Text)
    amo_agent_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    referrer: Mapped["User | None"] = relationship(remote_side=[id], lazy="selectin")


class SalesManager(Base):
    __tablename__ = "sales_managers"
    __table_args__ = (UniqueConstraint("code", name="uq_sales_managers_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    amo_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="telegram", index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sales_manager_id: Mapped[int | None] = mapped_column(ForeignKey("sales_managers.id"), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(255))
    debt_amount: Mapped[str | None] = mapped_column(String(255))
    relation_to_agent: Mapped[str | None] = mapped_column(String(255))
    agent_payout_phone: Mapped[str | None] = mapped_column(String(64))
    question_text: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    amo_lead_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    amo_contact_id: Mapped[int | None] = mapped_column(BigInteger)
    amo_pipeline_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    amo_status_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    amo_sync_status: Mapped[str | None] = mapped_column(String(32))
    amo_sync_error: Mapped[str | None] = mapped_column(Text)
    amo_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    staff_notified_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id], lazy="selectin")
    agent: Mapped[User | None] = relationship(foreign_keys=[agent_id], lazy="selectin")
    assigned_manager: Mapped[User | None] = relationship(foreign_keys=[assigned_manager_id], lazy="selectin")
    sales_manager: Mapped[SalesManager | None] = relationship(lazy="selectin")


class Bonus(Base):
    __tablename__ = "bonuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    agent: Mapped[User] = relationship(foreign_keys=[agent_id], lazy="selectin")
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by_admin_id], lazy="selectin")
    lead: Mapped[Lead | None] = relationship(lazy="selectin")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id], lazy="selectin")


class DeveloperSetting(Base):
    __tablename__ = "developer_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DeveloperParticipant(Base):
    __tablename__ = "developer_participants"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_developer_participants_platform_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="telegram", index=True, nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User | None] = relationship(lazy="selectin")


class DeveloperUserMute(Base):
    __tablename__ = "developer_user_mutes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    mute_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mute_staff_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mute_broadcasts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mute_bonus_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(lazy="selectin")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True, nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    sender_role: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    session: Mapped[ChatSession] = relationship(lazy="selectin")
    sender: Mapped[User] = relationship(lazy="selectin")


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    referred_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    referrer: Mapped[User] = relationship(foreign_keys=[referrer_id], lazy="selectin")
    referred: Mapped[User] = relationship(foreign_keys=[referred_id], lazy="selectin")


class UserState(Base):
    __tablename__ = "user_states"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_user_states_platform_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
