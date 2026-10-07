import hashlib, sqlite3, sys, secrets
from pathlib import Path
DB=Path('/data/portal.db')
def hp(p):
    salt=secrets.token_hex(16)
    d=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),310000).hex()
    return f'pbkdf2_sha256${salt}${d}'
if len(sys.argv)<3:
    print('Usage: python /app/cli.py reset-mfa USER | set-password USER MOTDEPASSE'); raise SystemExit(1)
cmd,user=sys.argv[1],sys.argv[2]; con=sqlite3.connect(DB)
if cmd=='reset-mfa':
    con.execute('UPDATE portal_users SET totp_secret=NULL,mfa_enabled=0,mfa_required=1,mfa_recovery_codes=NULL,mfa_pending_secret=NULL WHERE username=?',(user,)); con.commit(); print('MFA réinitialisée pour',user)
elif cmd=='set-password' and len(sys.argv)>=4:
    con.execute('UPDATE portal_users SET password_hash=? WHERE username=?',(hp(sys.argv[3]),user)); con.commit(); print('Mot de passe portail modifié pour',user)
else:
    print('Commande invalide'); raise SystemExit(1)
