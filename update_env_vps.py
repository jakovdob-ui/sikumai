"""מעדכן רק את ה-.env על ה-VPS"""
import paramiko, os
from dotenv import load_dotenv
load_dotenv()

HOST = '187.127.85.157'
USER = 'root'
PASS = 'QfFd976CCX3n#Er'

env_content = open(r'c:\Users\555\shulchan4\.env', encoding='utf-8').read()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print('מתחבר...')
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

sftp = ssh.open_sftp()
with sftp.open('/root/shulchan4/.env', 'w') as f:
    f.write(env_content)
print('✅ .env עודכן ב-shulchan4')

with sftp.open('/root/podsnap_bots/.env', 'w') as f:
    f.write(env_content)
print('✅ .env עודכן ב-podsnap_bots')

sftp.close()

# הפעל מחדש את האפליקציה
_, out, err = ssh.exec_command('systemctl restart shulchan4')
out.read(); err.read()
print('✅ shulchan4 service restarted')

ssh.close()
print('DONE')
