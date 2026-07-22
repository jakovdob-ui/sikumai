"""
Upload PodSnap bots to VPS — /root/podsnap_bots/
"""
import paramiko
import os
import sys

HOST     = "187.127.85.157"
USER     = "root"
PASSWORD = "QfFd976CCX3n#Er"
REMOTE   = "/root/podsnap_bots"
LOCAL    = r"C:\Users\555\shulchan4"

FILES = [
    "run_cmo.py",
    "run_sales_bot.py",
    "run_cs_bot.py",
    "run_pm_bot.py",
    "run_ceo_briefing.py",
]

# קורא .env מקומי ומעלה אותו כמו שהוא (כולל TELEGRAM_TOKEN ו-ADMIN_CHAT_ID)
ENV_PATH = os.path.join(LOCAL, ".env")
with open(ENV_PATH, encoding="utf-8") as _f:
    ENV_CONTENT = _f.read()

CRON_JOBS = [
    # CEO Briefing — כל יום ב-7:00
    "0 7 * * * cd /root/podsnap_bots && /root/podsnap_bots/venv/bin/python run_ceo_briefing.py >> /root/podsnap_bots/logs/ceo.log 2>&1",
    # CMO מיה — כל ראשון ב-9:00
    "0 9 * * 0 cd /root/podsnap_bots && /root/podsnap_bots/venv/bin/python run_cmo.py >> /root/podsnap_bots/logs/cmo.log 2>&1",
    # Sales Bot דני — כל יום ב-8:00
    "0 8 * * * cd /root/podsnap_bots && /root/podsnap_bots/venv/bin/python run_sales_bot.py >> /root/podsnap_bots/logs/sales.log 2>&1",
    # CS Bot רונה — כל יום ב-10:00
    "0 10 * * * cd /root/podsnap_bots && /root/podsnap_bots/venv/bin/python run_cs_bot.py >> /root/podsnap_bots/logs/cs.log 2>&1",
    # PM Bot אורי — כל ראשון ב-9:30
    "30 9 * * 0 cd /root/podsnap_bots && /root/podsnap_bots/venv/bin/python run_pm_bot.py >> /root/podsnap_bots/logs/pm.log 2>&1",
]


def run(ssh, cmd):
    _, out, err = ssh.exec_command(cmd)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    return o, e


def main():
    print(f"מתחבר ל-{HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    sftp = ssh.open_sftp()
    print("מחובר!")

    # ── [1] צור תיקיות ──────────────────────────────────────────
    print("\n[1/4] יוצר תיקיות...")
    for d in [REMOTE, f"{REMOTE}/logs", f"{REMOTE}/data"]:
        o, e = run(ssh, f"mkdir -p {d}")
        print(f"  mkdir {d}")

    # ── [2] העלה קבצים ──────────────────────────────────────────
    print("\n[2/4] מעלה קבצים...")
    for f in FILES:
        local  = os.path.join(LOCAL, f)
        remote = f"{REMOTE}/{f}"
        if not os.path.exists(local):
            print(f"  SKIP {f} (לא נמצא מקומית)")
            continue
        sftp.put(local, remote)
        print(f"  OK   {f}")

    # כתוב .env
    o, _ = run(ssh, f"cat > {REMOTE}/.env << 'ENVEOF'\n{ENV_CONTENT}\nENVEOF")
    print("  OK   .env")

    # ── [3] התקן חבילות ─────────────────────────────────────────
    print("\n[3/4] מתקין venv + חבילות...")
    cmds = [
        f"python3 -m venv {REMOTE}/venv",
        f"{REMOTE}/venv/bin/pip install --quiet google-generativeai psycopg2-binary httpx python-dotenv requests",
    ]
    for cmd in cmds:
        o, e = run(ssh, cmd)
        short = cmd.split("/")[-1][:50]
        print(f"  {short}: {'OK' if not e else e[:80]}")

    # ── [4] הגדר cron ────────────────────────────────────────────
    print("\n[4/4] מגדיר cron jobs...")
    o, _ = run(ssh, "crontab -l 2>/dev/null || echo ''")
    existing = o

    new_jobs = [j for j in CRON_JOBS if j not in existing]
    if not new_jobs:
        print("  Cron jobs כבר קיימים — מדלג")
    else:
        new_cron = existing.rstrip() + "\n" + "\n".join(new_jobs) + "\n"
        stdin_ch, _, _ = ssh.exec_command("crontab -")
        stdin_ch.write(new_cron)
        stdin_ch.channel.shutdown_write()
        print(f"  נוספו {len(new_jobs)} cron jobs:")
        for j in new_jobs:
            print(f"    {j[:80]}")

    # הצג crontab סופי
    o, _ = run(ssh, "crontab -l | grep podsnap")
    print(f"\n  PodSnap crons פעילים:\n  {o}")

    sftp.close()
    ssh.close()
    print("\nSUCCESS")


if __name__ == "__main__":
    main()
