"""בדיקת מצב ה-VPS"""
import paramiko

HOST = '187.127.85.157'
USER = 'root'
PASS = 'QfFd976CCX3n#Er'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)

def run(cmd, label=''):
    if label: print(f'\n=== {label} ===')
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip().encode('ascii', errors='replace').decode())
    if err: print('[ERR]', err.strip().encode('ascii', errors='replace').decode())

run('systemctl status shulchan4 --no-pager | head -20', 'shulchan4 service')
run('systemctl status nginx --no-pager | head -10', 'nginx service')
run('ss -tlnp', 'open ports')
run('nginx -v', 'nginx version')
run('journalctl -u shulchan4 --no-pager | tail -15', 'shulchan4 logs')

client.close()
