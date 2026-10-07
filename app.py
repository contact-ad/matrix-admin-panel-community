from __future__ import annotations
import base64, hashlib, hmac, io, json, os, secrets, sqlite3, time
from pathlib import Path
from functools import wraps
import pyotp, qrcode
import qrcode.image.svg
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from matrix_ops import add_user, deactivate_user, erase_user, get_instance, get_instances, instance_status, list_users, reactivate_user, reset_password

DB_PATH=Path('/data/portal.db')
APP_SECRET=os.environ.get('APP_SECRET') or secrets.token_hex(32)
BOOTSTRAP_ADMIN_USER=os.environ.get('BOOTSTRAP_ADMIN_USER','admin')
BOOTSTRAP_ADMIN_HASH=os.environ.get('BOOTSTRAP_ADMIN_HASH','')
PANEL_BRAND=os.environ.get('PANEL_BRAND','Matrix Admin Panel')
PANEL_TITLE=os.environ.get('PANEL_TITLE','Matrix Admin')
ISSUER=os.environ.get('MFA_ISSUER',PANEL_BRAND)
SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE','true').strip().lower() not in ('0','false','no','off')

app=Flask(__name__)
app.secret_key=APP_SECRET
app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1,x_host=1)
app.config.update(SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',PERMANENT_SESSION_LIFETIME=28800)
_login_attempts={}

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def ensure_column(c, table, name, decl):
    cols={r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
    if name not in cols:
        try:
            c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
        except sqlite3.OperationalError as e:
            # Deux workers peuvent démarrer simultanément pendant une migration.
            # Si l'autre a déjà créé la colonne, on continue normalement.
            if 'duplicate column name' not in str(e).lower():
                raise

def hash_password(p):
    salt=secrets.token_hex(16)
    d=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),310000).hex()
    return f'pbkdf2_sha256${salt}${d}'

def verify_password(p,stored):
    try:
        scheme,salt,digest=stored.split('$',2)
        got=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),310000).hex()
        return scheme=='pbkdf2_sha256' and hmac.compare_digest(got,digest)
    except Exception:return False

def init_db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS portal_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('superadmin','client')), client_slug TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        ensure_column(c,'portal_users','totp_secret','TEXT')
        ensure_column(c,'portal_users','mfa_enabled','INTEGER DEFAULT 0')
        ensure_column(c,'portal_users','mfa_required','INTEGER DEFAULT 0')
        ensure_column(c,'portal_users','mfa_pending_secret','TEXT')
        ensure_column(c,'portal_users','mfa_recovery_codes','TEXT')
        c.execute('''CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        actor_username TEXT, actor_role TEXT, client_slug TEXT, action TEXT NOT NULL,
        target TEXT, ip TEXT, success INTEGER NOT NULL DEFAULT 1, details TEXT)''')
        if c.execute('SELECT COUNT(*) FROM portal_users').fetchone()[0]==0:
            if not BOOTSTRAP_ADMIN_HASH: raise RuntimeError('BOOTSTRAP_ADMIN_HASH absent.')
            c.execute('INSERT INTO portal_users(username,password_hash,role,client_slug,mfa_required) VALUES(?,?,?,NULL,1)',
                      (BOOTSTRAP_ADMIN_USER,BOOTSTRAP_ADMIN_HASH,'superadmin'))
        c.execute("UPDATE portal_users SET mfa_required=1 WHERE role='superadmin' AND COALESCE(mfa_enabled,0)=0")

def ip_addr():
    return request.headers.get('X-Forwarded-For',request.remote_addr or 'unknown').split(',')[0].strip()

def audit(action,target='',success=True,details='',actor=None,client_slug=None):
    actor=actor or current_user()
    username=actor['username'] if actor else None
    role=actor['role'] if actor else None
    slug=client_slug if client_slug is not None else (actor['client_slug'] if actor else None)
    with db() as c:
        c.execute('INSERT INTO audit_log(actor_username,actor_role,client_slug,action,target,ip,success,details) VALUES(?,?,?,?,?,?,?,?)',
                  (username,role,slug,action,target,ip_addr(),1 if success else 0,details[:500]))

def current_user():
    uid=session.get('uid')
    if not uid:return None
    with db() as c:return c.execute('SELECT * FROM portal_users WHERE id=?',(uid,)).fetchone()

def csrf_token():
    if '_csrf' not in session:session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']

@app.context_processor
def globals_(): return {'csrf_token':csrf_token,'portal_user':current_user(),'panel_brand':PANEL_BRAND,'panel_title':PANEL_TITLE}

@app.before_request
def security_gate():
    if request.method=='POST' and request.endpoint not in ('login','mfa_verify'):
        a=session.get('_csrf',''); b=request.form.get('_csrf','')
        if not a or not hmac.compare_digest(a,b):abort(400,'Jeton CSRF invalide.')
    u=current_user()
    if u and int(u['mfa_required'] or 0) and not int(u['mfa_enabled'] or 0):
        allowed={'mfa_setup','logout','static'}
        if request.endpoint not in allowed:return redirect(url_for('mfa_setup'))

@app.after_request
def headers(r):
    r.headers['X-Frame-Options']='DENY'; r.headers['X-Content-Type-Options']='nosniff'; r.headers['Referrer-Policy']='same-origin'
    r.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    r.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none';"
    return r

def login_required(fn):
    @wraps(fn)
    def x(*a,**k):
        if not current_user():return redirect(url_for('login'))
        return fn(*a,**k)
    return x

def superadmin_required(fn):
    @wraps(fn)
    def x(*a,**k):
        u=current_user()
        if not u:return redirect(url_for('login'))
        if u['role']!='superadmin':abort(403)
        return fn(*a,**k)
    return x

def can_access(i):
    u=current_user(); return bool(u and (u['role']=='superadmin' or u['client_slug']==i.slug))

def recovery_hash(code): return hashlib.sha256(code.strip().upper().encode()).hexdigest()

def finish_login(u,method):
    session.clear(); session['uid']=u['id']; session.permanent=True; csrf_token()
    audit('login_success',target=u['username'],details=method,actor=u,client_slug=u['client_slug'])
    if int(u['mfa_required'] or 0) and not int(u['mfa_enabled'] or 0):return redirect(url_for('mfa_setup'))
    return redirect(url_for('dashboard'))

@app.route('/login',methods=['GET','POST'])
def login():
    if current_user():return redirect(url_for('dashboard'))
    if request.method=='POST':
        ip=ip_addr(); now=time.time(); tries=[t for t in _login_attempts.get(ip,[]) if now-t<300]
        if len(tries)>=8:
            flash('Trop de tentatives. Réessaie dans quelques minutes.','danger'); return render_template('login.html'),429
        username=request.form.get('username','').strip(); password=request.form.get('password','')
        with db() as c:u=c.execute('SELECT * FROM portal_users WHERE username=?',(username,)).fetchone()
        if u and verify_password(password,u['password_hash']):
            _login_attempts.pop(ip,None)
            if int(u['mfa_enabled'] or 0):
                session.clear(); session['preauth_uid']=u['id']; session.permanent=True
                return redirect(url_for('mfa_verify'))
            return finish_login(u,'password')
        tries.append(now); _login_attempts[ip]=tries
        audit('login_failed',target=username,success=False,details='bad_credentials',actor=None,client_slug=None)
        flash('Identifiant ou mot de passe incorrect.','danger')
    return render_template('login.html')

@app.route('/mfa/verify',methods=['GET','POST'])
def mfa_verify():
    uid=session.get('preauth_uid')
    if not uid:return redirect(url_for('login'))
    with db() as c:u=c.execute('SELECT * FROM portal_users WHERE id=?',(uid,)).fetchone()
    if not u:return redirect(url_for('login'))
    if request.method=='POST':
        code=request.form.get('code','').strip().upper().replace(' ','')
        ok=False; used_recovery=False
        if code.isdigit() and len(code)==6 and u['totp_secret']:
            ok=pyotp.TOTP(u['totp_secret']).verify(code,valid_window=1)
        if not ok and u['mfa_recovery_codes']:
            hashes=json.loads(u['mfa_recovery_codes'] or '[]'); h=recovery_hash(code)
            if h in hashes:
                hashes.remove(h); ok=True; used_recovery=True
                with db() as c:c.execute('UPDATE portal_users SET mfa_recovery_codes=? WHERE id=?',(json.dumps(hashes),u['id']))
        if ok:
            return finish_login(u,'recovery_code' if used_recovery else 'totp')
        audit('mfa_failed',target=u['username'],success=False,actor=u,client_slug=u['client_slug'])
        flash('Code MFA invalide.','danger')
    return render_template('mfa_verify.html',username=u['username'])

@app.route('/mfa/setup',methods=['GET','POST'])
@login_required
def mfa_setup():
    u=current_user()
    if int(u['mfa_enabled'] or 0):return render_template('mfa_setup.html',enabled=True)
    secret=u['mfa_pending_secret']
    if not secret:
        secret=pyotp.random_base32()
        with db() as c:c.execute('UPDATE portal_users SET mfa_pending_secret=? WHERE id=?',(secret,u['id']))
    if request.method=='POST':
        code=request.form.get('code','').strip()
        if pyotp.TOTP(secret).verify(code,valid_window=1):
            codes=['REC-'+secrets.token_hex(4).upper() for _ in range(8)]
            hashes=[recovery_hash(x) for x in codes]
            with db() as c:c.execute('UPDATE portal_users SET totp_secret=?,mfa_enabled=1,mfa_required=0,mfa_pending_secret=NULL,mfa_recovery_codes=? WHERE id=?',
                                     (secret,json.dumps(hashes),u['id']))
            audit('mfa_enabled',target=u['username'],actor=u,client_slug=u['client_slug'])
            return render_template('mfa_setup.html',enabled=True,recovery_codes=codes,just_enabled=True)
        flash('Le code saisi est invalide.','danger')
    uri=pyotp.TOTP(secret).provisioning_uri(name=u['username'],issuer_name=ISSUER)
    img=qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage)
    bio=io.BytesIO(); img.save(bio)
    qr='data:image/svg+xml;base64,'+base64.b64encode(bio.getvalue()).decode()
    return render_template('mfa_setup.html',enabled=False,secret=secret,qr=qr)

@app.route('/logout',methods=['POST'])
@login_required
def logout():
    u=current_user(); audit('logout',target=u['username'],actor=u,client_slug=u['client_slug']); session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    u=current_user(); instances=get_instances()
    if u['role']=='client':instances=[i for i in instances if i.slug==u['client_slug']]
    cards=[]
    for i in instances:
        try:active=sum(1 for x in list_users(i) if x['status']=='ACTIF')
        except Exception:active='?'
        cards.append({'inst':i,'status':instance_status(i),'active_users':active})
    return render_template('dashboard.html',cards=cards)

@app.route('/client/<slug>')
@login_required
def client_detail(slug):
    i=get_instance(slug)
    if not i:abort(404)
    if not can_access(i):abort(403)
    return render_template('client.html',inst=i,users=list_users(i),status=instance_status(i))

@app.route('/client/<slug>/user/add',methods=['POST'])
@login_required
def user_add(slug):
    i=get_instance(slug)
    if not i:abort(404)
    if not can_access(i):abort(403)
    u=current_user(); make_admin=u['role']=='superadmin' and request.form.get('make_admin')=='1'
    target=request.form.get('localpart','')
    try:
        uid=add_user(i,target,request.form.get('display_name',''),request.form.get('password',''),make_admin)
        audit('matrix_user_create',target=uid,details='admin=true' if make_admin else 'admin=false',actor=u,client_slug=i.slug)
        flash(f'Utilisateur créé : {uid}','success')
    except Exception as e:
        audit('matrix_user_create',target=target,success=False,details=str(e),actor=u,client_slug=i.slug); flash(f'Erreur : {e}','danger')
    return redirect(url_for('client_detail',slug=slug))

@app.route('/client/<slug>/user/deactivate',methods=['POST'])
@login_required
def user_deactivate(slug):
    i=get_instance(slug)
    if not i:abort(404)
    if not can_access(i):abort(403)
    target=request.form.get('user_id',''); portal=current_user()
    try:
        users={x['id']:x for x in list_users(i)}; item=users.get(target)
        if not item:raise ValueError('Utilisateur introuvable.')
        if item['status']!='ACTIF':raise ValueError('Compte déjà désactivé.')
        if portal['role']!='superadmin' and item['role']=='ADMIN':raise PermissionError('Un client ne peut pas désactiver un administrateur Matrix.')
        deactivate_user(i,target,False); audit('matrix_user_deactivate',target=target,details='erase=false',actor=portal,client_slug=i.slug); flash(f'Compte désactivé : {target}. Il pourra être réactivé avec un nouveau mot de passe.','success')
    except Exception as e:
        audit('matrix_user_deactivate',target=target,success=False,details=str(e),actor=portal,client_slug=i.slug); flash(f'Erreur : {e}','danger')
    return redirect(url_for('client_detail',slug=slug))

@app.route('/client/<slug>/user/reactivate',methods=['POST'])
@login_required
def user_reactivate(slug):
    i=get_instance(slug)
    if not i:abort(404)
    if not can_access(i):abort(403)
    target=request.form.get('user_id',''); portal=current_user()
    new=request.form.get('new_password',''); confirm=request.form.get('confirm_password','')
    try:
        users={x['id']:x for x in list_users(i)}; item=users.get(target)
        if not item:raise ValueError('Utilisateur introuvable.')
        if item['status']!='DESACTIVE':raise ValueError('Ce compte est déjà actif.')
        if portal['role']!='superadmin' and item['role']=='ADMIN':
            raise PermissionError('Un client ne peut pas réactiver un administrateur Matrix.')
        if new!=confirm:raise ValueError('Les mots de passe ne correspondent pas.')
        reactivate_user(i,target,new)
        audit('matrix_user_reactivate',target=target,details='new_password=true',actor=portal,client_slug=i.slug)
        flash(f'Compte réactivé : {target}. Le nouvel utilisateur devra se reconnecter et rejoindre à nouveau les salons nécessaires.','success')
    except Exception as e:
        audit('matrix_user_reactivate',target=target,success=False,details=str(e),actor=portal,client_slug=i.slug)
        flash(f'Erreur : {e}','danger')
    return redirect(url_for('client_detail',slug=slug))

@app.route('/client/<slug>/user/erase',methods=['POST'])
@superadmin_required
def user_erase(slug):
    i=get_instance(slug)
    if not i:abort(404)
    target=request.form.get('user_id',''); portal=current_user()
    confirmation=request.form.get('confirmation','').strip().upper()
    try:
        users={x['id']:x for x in list_users(i)}; item=users.get(target)
        if not item:raise ValueError('Utilisateur introuvable.')
        if confirmation!='EFFACER':
            raise ValueError('Confirmation incorrecte : saisis EFFACER.')
        result=erase_user(i,target)
        details="erase=true history_preserved=true messages_deleted=0 media_deleted=0"
        audit('matrix_user_erase',target=target,details=details,actor=portal,client_slug=i.slug)
        flash(
            f"Compte effacé : {target}. L'historique des salons, messages et fichiers partagés a été conservé.",
            'success'
        )
    except Exception as e:
        audit('matrix_user_erase',target=target,success=False,details=str(e),actor=portal,client_slug=i.slug)
        flash(f'Erreur : {e}','danger')
    return redirect(url_for('client_detail',slug=slug))

@app.route('/client/<slug>/user/password',methods=['POST'])
@login_required
def user_password(slug):
    i=get_instance(slug)
    if not i:abort(404)
    if not can_access(i):abort(403)
    target=request.form.get('user_id',''); portal=current_user(); new=request.form.get('new_password',''); confirm=request.form.get('confirm_password','')
    try:
        users={x['id']:x for x in list_users(i)}; item=users.get(target)
        if not item:raise ValueError('Utilisateur introuvable.')
        if item['status']!='ACTIF':raise ValueError('Compte désactivé.')
        if portal['role']!='superadmin' and item['role']=='ADMIN':raise PermissionError('Un client ne peut pas modifier le mot de passe d’un administrateur Matrix.')
        if new!=confirm:raise ValueError('Les mots de passe ne correspondent pas.')
        reset_password(i,target,new,True)
        audit('matrix_password_reset',target=target,details='logout_devices=true',actor=portal,client_slug=i.slug)
        flash(f'Mot de passe réinitialisé pour {target}. Toutes ses sessions ont été déconnectées.','success')
    except Exception as e:
        audit('matrix_password_reset',target=target,success=False,details=str(e),actor=portal,client_slug=i.slug); flash(f'Erreur : {e}','danger')
    return redirect(url_for('client_detail',slug=slug))

@app.route('/portal-users',methods=['GET','POST'])
@superadmin_required
def portal_users():
    admin=current_user()
    if request.method=='POST':
        username=request.form.get('username','').strip(); password=request.form.get('password',''); slug=request.form.get('client_slug','').strip()
        if not username or len(username)>64:flash('Identifiant portail invalide.','danger')
        elif len(password)<10:flash('Mot de passe : 10 caractères minimum.','danger')
        else:
            inst=get_instance(slug)
            if not inst or inst.is_primary:
                flash('Client invalide.','danger')
                return redirect(url_for('portal_users'))
            try:
                with db() as c:c.execute('INSERT INTO portal_users(username,password_hash,role,client_slug,mfa_required) VALUES(?,?,?,?,1)',(username,hash_password(password),'client',slug))
                audit('portal_access_create',target=username,details='MFA obligatoire',actor=admin,client_slug=slug); flash('Accès client créé. MFA obligatoire à la première connexion.','success')
            except sqlite3.IntegrityError:flash('Cet identifiant existe déjà.','danger')
    with db() as c:accounts=c.execute('SELECT id,username,role,client_slug,created_at,mfa_enabled,mfa_required FROM portal_users ORDER BY role DESC,username').fetchall()
    clients=[i for i in get_instances() if not i.is_ad]
    return render_template('portal_users.html',accounts=accounts,clients=clients)

@app.route('/portal-users/<int:user_id>/delete',methods=['POST'])
@superadmin_required
def portal_user_delete(user_id):
    admin=current_user()
    if admin['id']==user_id:flash('Tu ne peux pas supprimer ton propre compte.','danger'); return redirect(url_for('portal_users'))
    with db() as c:
        target=c.execute('SELECT * FROM portal_users WHERE id=?',(user_id,)).fetchone()
        if target and target['role']=='client': c.execute("DELETE FROM portal_users WHERE id=? AND role='client'",(user_id,))
    if target:audit('portal_access_delete',target=target['username'],actor=admin,client_slug=target['client_slug'])
    flash('Accès portail supprimé.','success'); return redirect(url_for('portal_users'))

@app.route('/portal-users/<int:user_id>/reset-mfa',methods=['POST'])
@superadmin_required
def portal_user_reset_mfa(user_id):
    admin=current_user()
    if admin['id']==user_id:flash('Pour ton propre compte, utilise la commande de secours serveur si nécessaire.','danger'); return redirect(url_for('portal_users'))
    with db() as c:
        target=c.execute('SELECT * FROM portal_users WHERE id=?',(user_id,)).fetchone()
        if target:c.execute('UPDATE portal_users SET totp_secret=NULL,mfa_enabled=0,mfa_required=1,mfa_pending_secret=NULL,mfa_recovery_codes=NULL WHERE id=?',(user_id,))
    if target:audit('portal_mfa_reset',target=target['username'],actor=admin,client_slug=target['client_slug'])
    flash('MFA réinitialisée. Le compte devra la reconfigurer à sa prochaine connexion.','success'); return redirect(url_for('portal_users'))

@app.route('/audit')
@login_required
def audit_view():
    u=current_user()
    with db() as c:
        if u['role']=='superadmin':rows=c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 500').fetchall()
        else:rows=c.execute('SELECT * FROM audit_log WHERE client_slug=? ORDER BY id DESC LIMIT 300',(u['client_slug'],)).fetchall()
    return render_template('audit.html',rows=rows)

init_db()
