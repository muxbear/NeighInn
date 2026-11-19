"""0010_neighbor_friends — 邻居好友体系。

- 新增 friend_blocks / friend_remarks；
- conversations 增加双向 pair、最近消息摘要、已读游标、清空时间；
- messages 增加 extra/read_at/deleted_at 与幂等唯一索引；
- 回填历史会话，合并重复 FRIEND 会话；
- 历史待处理好友申请中，双方同小区双认证的自动接受。

revision: 0010_neighbor_friends
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_neighbor_friends"
down_revision = "0009_broadcast_effective_window"
branch_labels = None
depends_on = None


def _fresh_schema(bind) -> bool:
    """0001 按当前 metadata 建表时，账号表已直接是 platform_users。"""
    tables = set(sa.inspect(bind).get_table_names())
    return "platform_users" in tables and "users" not in tables


def _drop_precreated_empty_tables(bind) -> None:
    """开发库 create_all 可能已建出 0010 的两张空表但未记录迁移版本。

    只有两张表都为空且无外键引用时才允许删除，由本迁移按旧表名重建；
    任一表有数据则中止，避免静默丢数据。
    """
    names = ("friend_blocks", "friend_remarks")
    existing = {name for name in names if name in sa.inspect(bind).get_table_names()}
    for name in existing:
        count = bind.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar()
        if count:
            raise RuntimeError(
                f"{name} 已有 {count} 行数据，不能自动重建；"
                "请人工确认数据来源后再执行迁移。"
            )
        refs = bind.execute(sa.text(
            "SELECT conrelid::regclass::text FROM pg_constraint "
            f"WHERE confrelid = '{name}'::regclass AND contype = 'f'"
        )).scalars().all()
        if refs:
            raise RuntimeError(f"{name} 被其他表引用：{refs}；请人工处理。")
    for name in existing:
        op.drop_table(name)


def _dedupe_friend_conversations(bind) -> None:
    """合并同一对用户的重复 FRIEND 会话，保留 id 最小的一条。"""
    rows = bind.execute(sa.text(
        """
        SELECT pair_low_id, pair_high_id, array_agg(id ORDER BY id) AS ids
        FROM conversations
        WHERE type = 'FRIEND'
          AND pair_low_id IS NOT NULL
          AND pair_high_id IS NOT NULL
        GROUP BY pair_low_id, pair_high_id
        HAVING count(*) > 1
        """
    )).fetchall()
    for _low, _high, ids in rows:
        keeper = int(ids[0])
        duplicated = [int(value) for value in ids[1:]]
        keeper_seq = int(bind.execute(
            sa.text("SELECT last_seq FROM conversations WHERE id = :id"),
            {"id": keeper},
        ).scalar() or 0)
        for duplicate in duplicated:
            duplicate_seq = int(bind.execute(
                sa.text("SELECT last_seq FROM conversations WHERE id = :id"),
                {"id": duplicate},
            ).scalar() or 0)
            bind.execute(
                sa.text(
                    """
                    UPDATE messages
                    SET conversation_id = :keeper,
                        seq = seq + :offset
                    WHERE conversation_id = :duplicate
                    """
                ),
                {"keeper": keeper, "offset": keeper_seq, "duplicate": duplicate},
            )
            bind.execute(
                sa.text("DELETE FROM conversations WHERE id = :id"),
                {"id": duplicate},
            )
            keeper_seq += duplicate_seq
        bind.execute(
            sa.text(
                """
                UPDATE conversations
                SET last_seq = :seq,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"seq": keeper_seq, "id": keeper},
        )


def _dedupe_item_conversations(bind) -> None:
    """合并同一物品 + 同一对用户的重复 ITEM 会话，保留 id 最小的一条。"""
    rows = bind.execute(sa.text(
        """
        SELECT item_id, pair_low_id, pair_high_id, array_agg(id ORDER BY id) AS ids
        FROM conversations
        WHERE type = 'ITEM'
          AND item_id IS NOT NULL
          AND pair_low_id IS NOT NULL
          AND pair_high_id IS NOT NULL
        GROUP BY item_id, pair_low_id, pair_high_id
        HAVING count(*) > 1
        """
    )).fetchall()
    for _item_id, _low, _high, ids in rows:
        keeper = int(ids[0])
        duplicated = [int(value) for value in ids[1:]]
        keeper_seq = int(bind.execute(
            sa.text("SELECT last_seq FROM conversations WHERE id = :id"),
            {"id": keeper},
        ).scalar() or 0)
        for duplicate in duplicated:
            duplicate_seq = int(bind.execute(
                sa.text("SELECT last_seq FROM conversations WHERE id = :id"),
                {"id": duplicate},
            ).scalar() or 0)
            bind.execute(
                sa.text(
                    """
                    UPDATE messages
                    SET conversation_id = :keeper,
                        seq = seq + :offset
                    WHERE conversation_id = :duplicate
                    """
                ),
                {"keeper": keeper, "offset": keeper_seq, "duplicate": duplicate},
            )
            bind.execute(
                sa.text("DELETE FROM conversations WHERE id = :id"),
                {"id": duplicate},
            )
            keeper_seq += duplicate_seq
        bind.execute(
            sa.text(
                """
                UPDATE conversations
                SET last_seq = :seq,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"seq": keeper_seq, "id": keeper},
        )


def upgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return
    _drop_precreated_empty_tables(bind)
    op.create_table(
        "friend_blocks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blocker_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("community_id", sa.BigInteger(), sa.ForeignKey("communities.id"), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="CHAT"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_friend_blocks_pair"),
    )
    op.create_index("ix_friend_blocks_blocker_id", "friend_blocks", ["blocker_id"])
    op.create_index("ix_friend_blocks_blocked_id", "friend_blocks", ["blocked_id"])
    op.create_index("ix_friend_blocks_status", "friend_blocks", ["status"])

    op.create_table(
        "friend_remarks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("peer_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("remark", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("owner_id", "peer_id", name="uq_friend_remarks_pair"),
    )
    op.create_index("ix_friend_remarks_owner_id", "friend_remarks", ["owner_id"])
    op.create_index("ix_friend_remarks_peer_id", "friend_remarks", ["peer_id"])

    op.add_column("conversations", sa.Column("pair_low_id", sa.BigInteger(), nullable=True))
    op.add_column("conversations", sa.Column("pair_high_id", sa.BigInteger(), nullable=True))
    op.add_column("conversations", sa.Column("last_message_type", sa.String(length=16),
                                              nullable=False, server_default="TEXT"))
    op.add_column("conversations", sa.Column("last_sender_id", sa.BigInteger(), nullable=True))
    op.add_column("conversations", sa.Column("last_message_at", sa.DateTime(timezone=True),
                                              nullable=True))
    op.add_column("conversations", sa.Column("last_read_seq_a", sa.BigInteger(),
                                              nullable=False, server_default="0"))
    op.add_column("conversations", sa.Column("last_read_seq_b", sa.BigInteger(),
                                              nullable=False, server_default="0"))
    op.add_column("conversations", sa.Column("cleared_at_a", sa.DateTime(timezone=True),
                                              nullable=True))
    op.add_column("conversations", sa.Column("cleared_at_b", sa.DateTime(timezone=True),
                                              nullable=True))

    op.execute(
        """
        UPDATE conversations
        SET pair_low_id = LEAST(user_a_id, user_b_id),
            pair_high_id = GREATEST(user_a_id, user_b_id),
            last_message_at = COALESCE(last_message_at, updated_at)
        WHERE pair_low_id IS NULL OR pair_high_id IS NULL
        """
    )
    _dedupe_friend_conversations(op.get_bind())
    _dedupe_item_conversations(op.get_bind())

    op.create_index("ix_conversations_pair_low_id", "conversations", ["pair_low_id"])
    op.create_index("ix_conversations_pair_high_id", "conversations", ["pair_high_id"])
    op.create_index("ix_conversations_user_a_updated", "conversations",
                    ["user_a_id", "updated_at"])
    op.create_index("ix_conversations_user_b_updated", "conversations",
                    ["user_b_id", "updated_at"])
    op.create_index(
        "uq_conversations_friend_pair", "conversations",
        ["pair_low_id", "pair_high_id"], unique=True,
        postgresql_where=sa.text("type = 'FRIEND'"),
    )
    op.create_index(
        "uq_conversations_item_pair", "conversations",
        ["item_id", "pair_low_id", "pair_high_id"], unique=True,
        postgresql_where=sa.text("type = 'ITEM'"),
    )

    op.add_column("messages", sa.Column(
        "extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'{}'"),
    ))
    op.add_column("messages", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # 清理重复 client_msg_id，保留最早一条，避免唯一索引创建失败。
    op.execute(
        """
        UPDATE messages m
        SET deleted_at = CURRENT_TIMESTAMP
        WHERE m.client_msg_id <> ''
          AND EXISTS (
              SELECT 1 FROM messages m2
              WHERE m2.conversation_id = m.conversation_id
                AND m2.sender_id = m.sender_id
                AND m2.client_msg_id = m.client_msg_id
                AND m2.id < m.id
          )
        """
    )
    op.create_index("ix_messages_conversation_seq", "messages",
                    ["conversation_id", "seq"])
    op.create_index("ix_messages_conversation_created", "messages",
                    ["conversation_id", "created_at"])
    op.create_index(
        "uq_messages_client_msg", "messages",
        ["conversation_id", "sender_id", "client_msg_id"], unique=True,
        postgresql_where=sa.text("client_msg_id <> ''"),
    )

    # 历史待处理申请：双方同小区且双认证时自动接受。
    op.execute(
        """
        UPDATE friend_requests fr
        SET status = 'ACCEPTED', handled_at = CURRENT_TIMESTAMP
        WHERE fr.status = 'PENDING'
          AND EXISTS (
              SELECT 1
              FROM residents ra
              JOIN users ua ON ua.id = ra.user_id
              WHERE ra.user_id = fr.from_user_id
                AND ra.status = 'ACTIVE'
                AND ra.certification_status = 'VERIFIED'
                AND ua.status = 'ACTIVE'
                AND ua.realname_status = 'VERIFIED'
          )
          AND EXISTS (
              SELECT 1
              FROM residents rb
              JOIN users ub ON ub.id = rb.user_id
              WHERE rb.user_id = fr.to_user_id
                AND rb.status = 'ACTIVE'
                AND rb.certification_status = 'VERIFIED'
                AND ub.status = 'ACTIVE'
                AND ub.realname_status = 'VERIFIED'
          )
          AND EXISTS (
              SELECT 1
              FROM residents ra
              JOIN residents rb ON rb.community_id = ra.community_id
              WHERE ra.user_id = fr.from_user_id
                AND rb.user_id = fr.to_user_id
                AND ra.status = 'ACTIVE'
                AND rb.status = 'ACTIVE'
          )
        """
    )


def downgrade() -> None:
    if _fresh_schema(op.get_bind()):
        return
    op.drop_index("uq_messages_client_msg", table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_conversation_seq", table_name="messages")
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "read_at")
    op.drop_column("messages", "extra")

    op.drop_index("uq_conversations_item_pair", table_name="conversations")
    op.drop_index("uq_conversations_friend_pair", table_name="conversations")
    op.drop_index("ix_conversations_user_b_updated", table_name="conversations")
    op.drop_index("ix_conversations_user_a_updated", table_name="conversations")
    op.drop_index("ix_conversations_pair_high_id", table_name="conversations")
    op.drop_index("ix_conversations_pair_low_id", table_name="conversations")
    for column in (
        "cleared_at_b",
        "cleared_at_a",
        "last_read_seq_b",
        "last_read_seq_a",
        "last_message_at",
        "last_sender_id",
        "last_message_type",
        "pair_high_id",
        "pair_low_id",
    ):
        op.drop_column("conversations", column)

    op.drop_index("ix_friend_remarks_peer_id", table_name="friend_remarks")
    op.drop_index("ix_friend_remarks_owner_id", table_name="friend_remarks")
    op.drop_table("friend_remarks")
    op.drop_index("ix_friend_blocks_status", table_name="friend_blocks")
    op.drop_index("ix_friend_blocks_blocked_id", table_name="friend_blocks")
    op.drop_index("ix_friend_blocks_blocker_id", table_name="friend_blocks")
    op.drop_table("friend_blocks")
