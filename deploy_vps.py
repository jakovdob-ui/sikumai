"""Deploy שולחן 4 to Hostinger VPS via Docker + Traefik"""
import paramiko
import os

HOST = '187.127.85.157'
USER = 'root'
PASS = 'QfFd976CCX3n#Er'
REMOTE_DIR = '/root/shulchan4'
LOCAL_DIR = r'c:\Users\555\shulchan4'

EXCLUDE = {'.git', '__pycache__', 'deploy_vps.py', 'venv', '.env',
           'check_vps.py', 'fix_vps.py', 'inspect_vps.py', 'run.bat',
           'node_modules', '.npm', 'package-lock.json'}

def ssh_run(client, cmd, label=''):
    if label: print(f'\n>> {label}')
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
    stdout.channel.set_combine_stderr(False)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out.strip(): print(out.strip().encode('ascii', errors='replace').decode())
    if err.strip(): print('[i]', err.strip().encode('ascii', errors='replace').decode()[:300])
    return out

def upload_dir(sftp, local, remote):
    try: sftp.mkdir(remote)
    except: pass
    for item in os.listdir(local):
        if item in EXCLUDE: continue
        lpath = os.path.join(local, item)
        rpath = remote + '/' + item
        if os.path.isdir(lpath):
            upload_dir(sftp, lpath, rpath)
        else:
            print(f'  upload: {item}')
            sftp.put(lpath, rpath)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print('מתחבר ל-VPS...')
client.connect(HOST, username=USER, password=PASS, timeout=15)
print('מחובר!')

# עלה קבצים
sftp = client.open_sftp()
print(f'\nמעלה קבצים ל-{REMOTE_DIR}...')
upload_dir(sftp, LOCAL_DIR, REMOTE_DIR)

# .env
env_content = open(r'c:\Users\555\shulchan4\.env', encoding='utf-8').read()
with sftp.open(REMOTE_DIR + '/.env', 'w') as f:
    f.write(env_content)
print('  upload: .env')
sftp.close()

# כתוב סקריפט שירוץ ברקע על השרת
build_script = f"""#!/bin/bash
set -e
LOG=/root/shulchan4_deploy.log
echo "=== Deploy started $(date) ===" > $LOG
systemctl stop shulchan4 2>/dev/null || true
systemctl disable shulchan4 2>/dev/null || true
fuser -k 5002/tcp 2>/dev/null || true
sleep 1
cd {REMOTE_DIR}
docker compose down 2>/dev/null || true
echo "Building..." >> $LOG
docker compose build --no-cache >> $LOG 2>&1
echo "Starting..." >> $LOG
docker compose up -d >> $LOG 2>&1
echo "=== Done $(date) ===" >> $LOG
docker compose ps >> $LOG 2>&1

# Set up daily cron job for LinkedIn agent
cat > /root/run_agent.sh << 'AGENTEOF'
#!/bin/bash
cd /root/shulchan4
docker compose exec -T shulchan4 python /app/run_linkedin_agent.py
AGENTEOF
chmod +x /root/run_agent.sh
(crontab -l 2>/dev/null | grep -v run_agent; echo "0 9 * * * /root/run_agent.sh >> /root/agent.log 2>&1") | crontab -
echo "Cron job installed (daily 09:00)" >> $LOG
"""

sftp2 = client.open_sftp()
with sftp2.open('/root/deploy_shulchan4.sh', 'w') as f:
    f.write(build_script)
sftp2.close()

ssh_run(client, 'chmod +x /root/deploy_shulchan4.sh')
print('\nמריץ build ברקע על השרת (ייקח ~2 דקות)...')
ssh_run(client, 'nohup /root/deploy_shulchan4.sh > /dev/null 2>&1 &')
client.close()

print('\nBuild רץ ברקע על השרת!')
print('   בעוד 2 דקות תוכל לגשת ל:')
print(f'   https://shulchan4.{HOST}.nip.io')
print('\n   לבדיקת סטטוס הרץ: python check_deploy.py')
