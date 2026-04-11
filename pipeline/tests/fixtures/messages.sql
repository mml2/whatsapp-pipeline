-- Schema matches the Go bridge exactly (github.com/lharries/whatsapp-mcp)
-- messages has a composite PK (id, chat_jid); no quoted_message_id column exists.

CREATE TABLE IF NOT EXISTS chats (
    jid               TEXT PRIMARY KEY,
    name              TEXT,
    last_message_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT,
    chat_jid        TEXT,
    sender          TEXT,
    content         TEXT,
    timestamp       TIMESTAMP,
    is_from_me      BOOLEAN,
    media_type      TEXT,
    filename        TEXT,
    url             TEXT,
    media_key       BLOB,
    file_sha256     BLOB,
    file_enc_sha256 BLOB,
    file_length     INTEGER,
    PRIMARY KEY (id, chat_jid),
    FOREIGN KEY (chat_jid) REFERENCES chats(jid)
);

-- -----------------------------------------------------------------------
-- Chats
-- -----------------------------------------------------------------------

INSERT INTO chats VALUES ('111111111111@g.us', 'Wayne Desi Gals', '2024-01-15T14:05:00');
INSERT INTO chats VALUES ('999999999999@g.us', 'Other Group',     '2024-01-15T10:12:00');

-- -----------------------------------------------------------------------
-- Wayne Desi Gals messages
-- -----------------------------------------------------------------------

-- msg_001: QUESTION — high confidence (service noun + request verb + location + contact language)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_001', '111111111111@g.us', 'Priya',
        'anyone know a good plumber near Karama? need contact number',
        '2024-01-15T10:00:00', 0, 'text');

-- msg_002: QUESTION — low confidence (abbreviated, single weak signal)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_002', '111111111111@g.us', 'Sunita',
        'anyone know AC guy',
        '2024-01-15T10:05:00', 0, 'text');

-- msg_003: ANSWER — temporal link to msg_001 (no quoted_message_id in this bridge)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_003', '111111111111@g.us', 'Reema',
        'Try Ahmed Plumbing, call him on 050 123 4567',
        '2024-01-15T10:10:00', 0, 'text');

-- msg_004: ANSWER — temporal link to msg_002 (within 120 min)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_004', '111111111111@g.us', 'Farah',
        'I know someone good, his number is +971559876543',
        '2024-01-15T10:15:00', 0, 'text');

-- msg_005: CHAT — emoji greeting
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_005', '111111111111@g.us', 'Meena',
        'Good morning everyone 🌞',
        '2024-01-15T10:20:00', 0, 'text');

-- msg_006: ANNOUNCEMENT — community broadcast
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_006', '111111111111@g.us', 'Admin',
        'Community meetup this Saturday at 6pm at the community centre, all welcome!',
        '2024-01-15T10:25:00', 0, 'text');

-- msg_007: ANSWER — vcard media type
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename)
VALUES ('msg_007', '111111111111@g.us', 'Deepa',
        NULL, '2024-01-15T10:30:00', 0, 'vcard', 'ahmed_plumbing.vcf');

-- msg_008: ANSWER — image of business card
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename)
VALUES ('msg_008', '111111111111@g.us', 'Layla',
        NULL, '2024-01-15T10:35:00', 0, 'image', 'business_card.jpg');

-- msg_009: ANSWER — orphan (no question within 120 min — sent 4 hours later)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_009', '111111111111@g.us', 'Noor',
        'Try this number: 04-123 4567',
        '2024-01-15T14:00:00', 0, 'text');

-- msg_010: QUESTION — from own account (is_from_me=1, still processed)
INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_010', '111111111111@g.us', 'Me',
        'does anyone know a good dentist in Jumeirah?',
        '2024-01-15T14:05:00', 1, 'text');

-- -----------------------------------------------------------------------
-- Other Group messages — must NEVER appear in pipeline output
-- -----------------------------------------------------------------------

INSERT INTO messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type)
VALUES ('msg_011', '999999999999@g.us', 'Stranger',
        'anyone know a plumber? need number urgently near downtown',
        '2024-01-15T10:12:00', 0, 'text');
