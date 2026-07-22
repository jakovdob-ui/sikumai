import paramiko
HOST = '187.127.85.157'
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username='root', password='QfFd976CCX3n#Er', timeout=15)

def run(cmd):
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    return out.encode('ascii', errors='replace').decode()

print(run('cat /root/bot_template/docker-compose.trading.yml'))
print('---')
print(run('ls /root/podsnap_bots/'))
print(run('cat /root/podsnap_bots/docker-compose.yml 2>/dev/null || echo "no file"'))
print('---')
print(run('docker ps --format "table {{.Names}}\\t{{.Ports}}"'))
client.close()
