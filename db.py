import os
import psycopg2
import psycopg2.extras
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', '')


def _conn():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL חסר ב-.env')
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def init():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    plan TEXT NOT NULL DEFAULT 'free',
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    portal_url TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS usage_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    month TEXT NOT NULL,
                    transcript_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, month)
                )
            ''')
        c.commit()


def _row(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


def get_by_email(email):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return _row(cur, 'SELECT * FROM users WHERE email=%s', (email,))


def get_by_id(uid):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return _row(cur, 'SELECT * FROM users WHERE id=%s', (uid,))


def create(email, pw_hash, name=''):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                'INSERT INTO users (email, password_hash, name) VALUES (%s,%s,%s) RETURNING id',
                (email, pw_hash, name)
            )
            uid = cur.fetchone()[0]
        c.commit()
        return uid


def month_usage(uid):
    month = datetime.now().strftime('%Y-%m')
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                'SELECT transcript_count FROM usage_log WHERE user_id=%s AND month=%s',
                (uid, month)
            )
            row = cur.fetchone()
            return row[0] if row else 0


def inc_usage(uid):
    month = datetime.now().strftime('%Y-%m')
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                INSERT INTO usage_log (user_id, month, transcript_count) VALUES (%s,%s,1)
                ON CONFLICT (user_id, month)
                DO UPDATE SET transcript_count = usage_log.transcript_count + 1
            ''', (uid, month))
        c.commit()


def set_pro(uid, customer_id, sub_id, portal_url=''):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "UPDATE users SET plan='pro', stripe_customer_id=%s, stripe_subscription_id=%s, portal_url=%s WHERE id=%s",
                (customer_id, sub_id, portal_url, uid)
            )
        c.commit()


def set_free(uid):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "UPDATE users SET plan='free', stripe_subscription_id=NULL WHERE id=%s",
                (uid,)
            )
        c.commit()


def get_by_payment_customer(customer_id):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return _row(cur, 'SELECT * FROM users WHERE stripe_customer_id=%s', (customer_id,))
