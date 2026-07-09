import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', '')

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError('DATABASE_URL חסר ב-.env')
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL, sslmode='require')
    return _pool

class _conn:
    def __enter__(self):
        self._c = _get_pool().getconn()
        return self._c
    def __exit__(self, *_):
        _get_pool().putconn(self._c)


def init():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS reset_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    token TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, video_id)
                )
            ''')
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
            cur.execute('''
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS linkedin_access_token TEXT,
                ADD COLUMN IF NOT EXISTS linkedin_token_expiry TIMESTAMP,
                ADD COLUMN IF NOT EXISTS linkedin_urn TEXT
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS linkedin_posts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    post_urn TEXT,
                    content TEXT NOT NULL,
                    video_id TEXT,
                    style TEXT NOT NULL DEFAULT 'A',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS auto_posted_videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    post_content TEXT NOT NULL,
                    posted_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    opportunities TEXT NOT NULL DEFAULT '',
                    lang TEXT NOT NULL DEFAULT 'he',
                    created_at TIMESTAMP DEFAULT NOW()
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


def set_plan(uid, plan):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("UPDATE users SET plan=%s WHERE id=%s", (plan, uid))
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


def create_reset_token(uid):
    import secrets
    from datetime import datetime, timedelta
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=1)
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('DELETE FROM reset_tokens WHERE user_id=%s', (uid,))
            cur.execute(
                'INSERT INTO reset_tokens (user_id, token, expires_at) VALUES (%s,%s,%s)',
                (uid, token, expires_at)
            )
        c.commit()
    return token


def get_reset_token(token):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT * FROM reset_tokens WHERE token=%s AND expires_at > NOW()',
                (token,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_reset_token(token):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('DELETE FROM reset_tokens WHERE token=%s', (token,))
        c.commit()


def update_password(uid, pw_hash):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('UPDATE users SET password_hash=%s WHERE id=%s', (pw_hash, uid))
        c.commit()


def save_episode(uid, video_id, title, summary=''):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                INSERT INTO episodes (user_id, video_id, title, summary)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, video_id)
                DO UPDATE SET title=EXCLUDED.title, summary=EXCLUDED.summary, created_at=NOW()
            ''', (uid, video_id, title, summary))
        c.commit()


def get_episodes(uid, limit=20):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT video_id, title, summary, created_at FROM episodes WHERE user_id=%s ORDER BY created_at DESC LIMIT %s',
                (uid, limit)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def save_linkedin_token(uid, token, expiry, urn):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                'UPDATE users SET linkedin_access_token=%s, linkedin_token_expiry=%s, linkedin_urn=%s WHERE id=%s',
                (token, expiry, urn, uid)
            )
        c.commit()


def save_linkedin_post(uid, post_urn, content, video_id, style):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                'INSERT INTO linkedin_posts (user_id, post_urn, content, video_id, style) VALUES (%s,%s,%s,%s,%s)',
                (uid, post_urn, content, video_id, style)
            )
        c.commit()


def get_linkedin_stats(uid):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT style, COUNT(*) as posts FROM linkedin_posts WHERE user_id=%s GROUP BY style',
                (uid,)
            )
            return [dict(r) for r in cur.fetchall()]


def was_auto_posted(video_id):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('SELECT 1 FROM auto_posted_videos WHERE video_id=%s', (video_id,))
            return cur.fetchone() is not None


def mark_auto_posted(video_id, channel_id, title, content):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                INSERT INTO auto_posted_videos (video_id, channel_id, title, post_content)
                VALUES (%s,%s,%s,%s) ON CONFLICT (video_id) DO NOTHING
            ''', (video_id, channel_id, title, content))
        c.commit()


def get_auto_posts(limit=10):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT video_id, channel_id, title, post_content, posted_at FROM auto_posted_videos ORDER BY posted_at DESC LIMIT %s',
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]


def create_share(share_id, video_id, title, summary, opportunities, lang='he'):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('''
                INSERT INTO shares (id, video_id, title, summary, opportunities, lang)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
            ''', (share_id, video_id, title, summary, opportunities, lang))
        c.commit()


def get_share(share_id):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM shares WHERE id=%s', (share_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def ping():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute('SELECT 1')


def create_job(job_id, user_id, video_url):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, user_id, video_url, status) VALUES (%s,%s,%s,'pending')",
                (job_id, str(user_id), video_url)
            )
        c.commit()


def update_job(job_id, status, result=None):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(
                'UPDATE jobs SET status=%s, result=%s WHERE id=%s',
                (status, psycopg2.extras.Json(result) if result is not None else None, job_id)
            )
        c.commit()


def get_job(job_id):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT id, user_id, status, result FROM jobs WHERE id=%s', (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def daily_stats():
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours'")
            new_users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE plan='pro'")
            pro = cur.fetchone()[0]
            return {'new_users': new_users, 'total': total, 'pro': pro, 'free': total - pro}
