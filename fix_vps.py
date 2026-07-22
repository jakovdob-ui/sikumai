"""תיקון שרת shulchan4 + הגדרת Traefik"""
import paramiko

HOST = '187.127.85.157'
USER = 'root'
PASS = 'QfFd976CCX3n#Er'
REMOTE_DIR = '/root/shulchan4'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print('מתחבר...')
client.connect(HOST, username=USER, password=PASS, timeout=15)

def run(cmd, label=''):
    if label: print(f'\n>> {label}')
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip().encode('ascii', errors='replace').decode())
    if err and '[ERR]' not in err: print('[i]', err.strip().encode('ascii', errors='replace').decode()[:200])
    return out

# שלב 1: הרוג את כל התהליכים הישנים על פורט 5002
print('\n1. מסיר תהליכים ישנים על פורט 5002...')
run('fuser -k 5002/tcp 2>/dev/null || true')
run('pkill -f "gunicorn.*5002" 2>/dev/null || true')
run('sleep 2')

# שלב 2: הפעל מחדש את השירות
print('\n2. מפעיל מחדש את shulchan4...')
run('systemctl daemon-reload')
run('systemctl restart shulchan4')
run('sleep 4')
run('systemctl status shulchan4 --no-pager | head -10', 'סטטוס שירות')

# שלב 3: הגדר Traefik labels עם docker-compose דינמי
# Traefik ב-Hostinger עובד דרך קבצי config דינמיים
print('\n3. מגדיר Traefik לנתב ל-shulchan4...')

# בדוק איפה Traefik רץ
run('find /root /opt /etc -name "docker-compose*.yml" 2>/dev/null | head -10', 'docker-compose files')
run('ls /root/', 'תיקיית root')
run('cat /proc/1358/cmdline 2>/dev/null | tr "\\0" " "', 'Traefik args')
run('ls /etc/traefik/ 2>/dev/null || ls /opt/traefik/ 2>/dev/null || echo "no traefik config dir found"', 'Traefik config')

# שלב 4: בדוק פורטים פתוחים
run('ss -tlnp | grep -E "80|443|5002"', 'פורטים פתוחים')

client.close()
print('\nסיום בדיקה!')
