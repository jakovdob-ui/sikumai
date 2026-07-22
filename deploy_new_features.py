"""
Deploy only the new/changed files to VPS.
Faster than full deploy — only copies what changed.
"""
import paramiko
import os
import time

HOST = '187.127.85.157'
USER = 'root'
PASS = 'QfFd976CCX3n#Er'
REMOTE_DIR = '/root/shulchan4'
LOCAL_DIR = r'c:\Users\555\shulchan4'

FILES_TO_UPLOAD = [
    ('app.py',                          f'{REMOTE_DIR}/app.py'),
    ('ai_utils.py',                     f'{REMOTE_DIR}/ai_utils.py'),
    ('db.py',                           f'{REMOTE_DIR}/db.py'),
    ('requirements.txt',                f'{REMOTE_DIR}/requirements.txt'),
    ('Dockerfile',                      f'{REMOTE_DIR}/Dockerfile'),
    ('run_linkedin_agent.py',           f'{REMOTE_DIR}/run_linkedin_agent.py'),
    ('run_cmo.py',                      f'{REMOTE_DIR}/run_cmo.py'),
    ('run_pm_bot.py',                   f'{REMOTE_DIR}/run_pm_bot.py'),
    ('run_sales_bot.py',                f'{REMOTE_DIR}/run_sales_bot.py'),
    ('run_cs_bot.py',                   f'{REMOTE_DIR}/run_cs_bot.py'),
    (r'templates\index.html',           f'{REMOTE_DIR}/templates/index.html'),
    (r'templates\landing.html',         f'{REMOTE_DIR}/templates/landing.html'),
    (r'templates\landing_en.html',      f'{REMOTE_DIR}/templates/landing_en.html'),
    (r'templates\share.html',           f'{REMOTE_DIR}/templates/share.html'),
]


def connect_with_retry(max_attempts=5):
    for attempt in range(1, max_attempts + 1):
        try:
            print(f'מנסה להתחבר... ניסיון {attempt}/{max_attempts}')
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                HOST,
                username=USER,
                password=PASS,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
                look_for_keys=False,
                allow_agent=False,
            )
            print('מחובר!')
            return client
        except Exception as e:
            print(f'  נכשל: {e}')
            if attempt < max_attempts:
                wait = attempt * 5
                print(f'  ממתין {wait} שניות...')
                time.sleep(wait)
    raise RuntimeError('לא הצלחתי להתחבר לשרת אחרי כל הניסיונות')


def ssh_run(client, cmd, label=''):
    if label:
        print(f'\n>> {label}')
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out.strip():
        print(out.strip()[:1000])
    if err.strip():
        print('[stderr]', err.strip()[:500])
    return out


def main():
    client = connect_with_retry()

    sftp = client.open_sftp()
    print(f'\nמעלה {len(FILES_TO_UPLOAD)} קבצים...')

    for local_rel, remote_path in FILES_TO_UPLOAD:
        local_path = os.path.join(LOCAL_DIR, local_rel)
        if not os.path.exists(local_path):
            print(f'  SKIP (לא קיים): {local_rel}')
            continue
        try:
            sftp.put(local_path, remote_path)
            print(f'  ✓ {local_rel}')
        except Exception as e:
            print(f'  ✗ {local_rel}: {e}')

    sftp.close()
    print('\nכל הקבצים הועלו!')

    print('\nמבצע docker build על השרת...')
    ssh_run(client,
        f'cd {REMOTE_DIR} && docker compose build shulchan4 2>&1 | tail -20',
        'docker compose build')

    print('\nמפעיל מחדש...')
    ssh_run(client,
        f'cd {REMOTE_DIR} && docker compose up -d shulchan4 2>&1',
        'docker compose up -d')

    time.sleep(3)
    print('\nבודק סטטוס...')
    ssh_run(client,
        f'cd {REMOTE_DIR} && docker compose ps shulchan4',
        'docker compose ps')

    client.close()
    print('\nDeploy הושלם! בדוק getpodsnap.com/en')


if __name__ == '__main__':
    main()
