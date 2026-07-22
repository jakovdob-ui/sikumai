"""בדוק סטטוס deploy"""
import paramiko
HOST = '187.127.85.157'
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username='root', password='QfFd976CCX3n#Er', timeout=15)

def run(cmd):
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    combined = (out + err).encode('ascii', errors='replace').decode()
    if combined.strip(): print(combined.strip())

print('=== לוג deploy ===')
run('tail -30 /root/shulchan4_deploy.log 2>/dev/null || echo "עדיין לא התחיל"')
print('\n=== Docker containers ===')
run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print('\n=== לוגי shulchan4 ===')
run('cd /root/shulchan4 && docker compose logs --tail=10 2>/dev/null || echo "container לא רץ"')

client.close()
