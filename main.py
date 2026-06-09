# -*- coding: utf-8 -*-
"""
================================================================
  IFRI MentorLink — Serveur (back-end)
================================================================
  Lancement :  python3 main.py
  Adresse   :  http://localhost:5000

  Fonctionnalités back-end :
    - Authentification utilisateur (inscription / connexion)
    - Authentification admin (mot de passe partagé)
    - Profil, compétences, disponibilités, annonces
    - Messagerie temps réel (Socket.IO) + notifications push
    - Matching mentor ↔ mentoré (DUAL : pour moi / par moi)
    - Réinitialisation de mot de passe (email + téléphone)
    - Dashboard admin (gestion filières / matières / programmes)
================================================================
"""

import os
import re
from datetime import datetime
from flask import Flask, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pymysql
import pymysql.cursors


# ============================================================
#  CONFIGURATION
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=None, template_folder='.')
app.secret_key = os.environ.get('MENTORLINK_SECRET', 'dev-secret-ifri-mentorlink')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

DB_CONFIG = {
    'host':     os.environ.get('DB_HOST', 'localhost'),
    'user':     os.environ.get('DB_USER', 'mentorlink'),
    'password': os.environ.get('DB_PASS', 'MentorLink_2026!'),
    'database': os.environ.get('DB_NAME', 'mentorlink'),
    'charset':  'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': False,
}

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
JOURS = {'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'}

# Mot de passe partagé pour les administrateurs IFRI
ADMIN_PASSWORD = 'IFRI_Motorlink.2526'


# ============================================================
#  HELPERS
# ============================================================
def db():
    return pymysql.connect(**DB_CONFIG)


def ok(payload=None, **extra):
    body = {'ok': True}
    if payload: body.update(payload)
    if extra:   body.update(extra)
    return jsonify(body)


def err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


@app.errorhandler(pymysql.Error)
def _db_error(e):
    import traceback; traceback.print_exc()
    return jsonify({'ok': False, 'error': f'Erreur base de données : {e.args[1] if len(e.args)>1 else e}'}), 500


def current_uid():
    return session.get('uid')


def is_admin():
    return bool(session.get('admin'))


def require_login():
    uid = current_uid()
    if not uid:
        return None, err('Non connecté.', 401)
    return uid, None


def require_admin():
    if not is_admin():
        return err('Accès administrateur requis.', 403)
    return None


def parse_tel(raw):
    digits = ''.join(c for c in str(raw) if c.isdigit())
    return int(digits) if len(digits) == 10 else None


def format_tel(n):
    return str(n).zfill(10) if n is not None else ''


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def fetch_user(cur, uid):
    """Profil complet de l'utilisateur (pour soi-même : ME)."""
    cur.execute("""
        SELECT u.id_User, u.nom, u.prenom, u.tel, u.email, u.photo, u.bio,
               u.id_Fil, u.id_Niv, f.lib_Fil AS filiere, n.lib_Niv AS niveau
        FROM utilisateur u
        JOIN filiere f ON u.id_Fil = f.id_Fil
        JOIN niveau  n ON u.id_Niv = n.id_Niv
        WHERE u.id_User = %s
    """, (uid,))
    u = cur.fetchone()
    if not u: return None
    u['tel']   = format_tel(u['tel'])
    u['bio']   = u['bio'] or ''
    u['photo'] = ('/' + u['photo']) if u['photo'] else None

    cur.execute("""
        SELECT m.lib_Mat, c.maitrise
        FROM competence c JOIN matiere m ON c.id_Mat = m.id_Mat
        WHERE c.id_User = %s ORDER BY m.lib_Mat
    """, (uid,))
    rows = cur.fetchall()
    u['forts']   = [r['lib_Mat'] for r in rows if r['maitrise']]
    u['lacunes'] = [r['lib_Mat'] for r in rows if not r['maitrise']]

    cur.execute("""
        SELECT id_Dispo AS id, jour, heure_debut, heure_fin
        FROM disponibilite WHERE id_User = %s ORDER BY id_Dispo
    """, (uid,))
    u['dispos'] = [{
        'id':    r['id'],
        'jour':  r['jour'],
        'debut': str(r['heure_debut'])[:5],
        'fin':   str(r['heure_fin'])[:5],
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT a.id_Annonce AS id, a.type_annonce AS type, a.format,
               a.details, a.date_pub, m.lib_Mat AS mat
        FROM annonce a JOIN matiere m ON a.id_Mat = m.id_Mat
        WHERE a.id_User = %s ORDER BY a.date_pub DESC
    """, (uid,))
    u['annonces'] = [{
        'id': r['id'], 'type': r['type'], 'format': r['format'],
        'mat': r['mat'], 'details': r['details'] or '',
        'date_pub': r['date_pub'].isoformat() if r['date_pub'] else None
    } for r in cur.fetchall()]
    return u


def fetch_user_public(cur, uid):
    """Profil public d'un autre utilisateur (pour 'Voir profil' depuis la messagerie).
       Pas d'email ni de téléphone. Inclut forts, lacunes, dispos, annonces."""
    cur.execute("""
        SELECT u.id_User AS id, u.nom, u.prenom, u.photo, u.bio,
               f.lib_Fil AS filiere, n.lib_Niv AS niveau
        FROM utilisateur u
        JOIN filiere f ON u.id_Fil = f.id_Fil
        JOIN niveau  n ON u.id_Niv = n.id_Niv
        WHERE u.id_User = %s
    """, (uid,))
    u = cur.fetchone()
    if not u: return None
    u['bio']   = u['bio'] or ''
    u['photo'] = ('/' + u['photo']) if u['photo'] else None

    cur.execute("""
        SELECT m.lib_Mat, c.maitrise FROM competence c
        JOIN matiere m ON c.id_Mat = m.id_Mat
        WHERE c.id_User=%s ORDER BY m.lib_Mat
    """, (uid,))
    rows = cur.fetchall()
    u['forts']   = [r['lib_Mat'] for r in rows if r['maitrise']]
    u['lacunes'] = [r['lib_Mat'] for r in rows if not r['maitrise']]

    cur.execute("""SELECT jour, heure_debut, heure_fin FROM disponibilite
                   WHERE id_User=%s ORDER BY id_Dispo""", (uid,))
    u['dispos'] = [{
        'jour':  r['jour'],
        'debut': str(r['heure_debut'])[:5],
        'fin':   str(r['heure_fin'])[:5],
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT a.type_annonce AS type, a.format, a.details, a.date_pub, m.lib_Mat AS mat
        FROM annonce a JOIN matiere m ON a.id_Mat = m.id_Mat
        WHERE a.id_User=%s ORDER BY a.date_pub DESC
    """, (uid,))
    u['annonces'] = [{
        'type': r['type'], 'format': r['format'],
        'mat': r['mat'], 'details': r['details'] or '',
        'date_pub': r['date_pub'].isoformat() if r['date_pub'] else None
    } for r in cur.fetchall()]
    return u


def fetch_user_brief(cur, uid):
    cur.execute("""
        SELECT u.id_User AS id, u.nom, u.prenom, u.photo,
               f.lib_Fil AS filiere, n.lib_Niv AS niveau
        FROM utilisateur u
        JOIN filiere f ON u.id_Fil = f.id_Fil
        JOIN niveau  n ON u.id_Niv = n.id_Niv
        WHERE u.id_User = %s
    """, (uid,))
    u = cur.fetchone()
    if not u: return None
    u['photo'] = ('/' + u['photo']) if u['photo'] else None
    return u


def matieres_for_user(cur, id_fil, id_niv):
    """Renvoie la liste des matières disponibles pour un utilisateur
       en fonction de sa filière et de son niveau (via cours_matiere)."""
    cur.execute("""
        SELECT DISTINCT m.lib_Mat
        FROM cours c
        JOIN cours_matiere cm ON cm.id_Cours = c.id_Cours
        JOIN matiere m ON m.id_Mat = cm.id_Mat
        WHERE c.id_Fil = %s AND c.id_Niv = %s
        ORDER BY m.lib_Mat
    """, (id_fil, id_niv))
    return [r['lib_Mat'] for r in cur.fetchall()]


# ============================================================
#  PAGES STATIQUES
# ============================================================
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/app.js')
def app_js():
    return send_from_directory(BASE_DIR, 'app.js', mimetype='application/javascript')


@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ============================================================
#  RÉFÉRENTIELS
# ============================================================
@app.get('/api/refs')
def api_refs():
    """Renvoie les listes pour les formulaires.
       Si l'utilisateur est connecté, les matières sont filtrées
       selon sa filière et son niveau (pour les forts/lacunes).
       Sinon, on renvoie toutes les matières (inscription)."""
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT lib_Fil FROM filiere ORDER BY lib_Fil')
            filieres = [r['lib_Fil'] for r in cur.fetchall()]
            cur.execute('SELECT lib_Niv FROM niveau ORDER BY id_Niv')
            niveaux  = [r['lib_Niv'] for r in cur.fetchall()]

            uid = current_uid()
            if uid:
                cur.execute('SELECT id_Fil, id_Niv FROM utilisateur WHERE id_User=%s', (uid,))
                u = cur.fetchone()
                if u:
                    matieres = matieres_for_user(cur, u['id_Fil'], u['id_Niv'])
                else:
                    matieres = []
            else:
                cur.execute('SELECT lib_Mat FROM matiere ORDER BY lib_Mat')
                matieres = [r['lib_Mat'] for r in cur.fetchall()]
        return ok({'filieres': filieres, 'niveaux': niveaux, 'matieres': matieres})
    finally:
        conn.close()


# ============================================================
#  AUTHENTIFICATION UTILISATEUR
# ============================================================
@app.post('/api/signup')
def api_signup():
    d = request.get_json(silent=True) or {}
    prenom = (d.get('prenom') or '').strip()
    nom    = (d.get('nom')    or '').strip()
    email  = (d.get('email')  or '').strip().lower()
    pwd    = d.get('pass') or ''
    fil    = (d.get('filiere') or '').strip()
    niv    = (d.get('niveau')  or '').strip()
    tel    = parse_tel(d.get('tel'))

    if not (prenom and nom and email and pwd and fil and niv):
        return err('Tous les champs sont obligatoires.')
    if tel is None:
        return err('Le téléphone doit faire exactement 10 chiffres.')
    if len(pwd) < 6:
        return err('Le mot de passe doit faire au moins 6 caractères.')

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_User FROM utilisateur WHERE email=%s OR tel=%s LIMIT 1', (email, tel))
            if cur.fetchone():
                return err('Email ou téléphone déjà utilisé.')

            cur.execute('SELECT id_Fil FROM filiere WHERE lib_Fil=%s', (fil,))
            r = cur.fetchone()
            if not r: return err('Filière inconnue.')
            id_fil = r['id_Fil']

            cur.execute('SELECT id_Niv FROM niveau WHERE lib_Niv=%s', (niv,))
            r = cur.fetchone()
            if not r: return err('Niveau inconnu.')
            id_niv = r['id_Niv']

            mdp_hash = generate_password_hash(pwd)
            cur.execute("""
                INSERT INTO utilisateur (nom, prenom, tel, email, mdp, id_Fil, id_Niv)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (nom, prenom, tel, email, mdp_hash, id_fil, id_niv))
            uid = cur.lastrowid
            conn.commit()
            session['uid'] = uid
            session.pop('admin', None)
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


@app.post('/api/login')
def api_login():
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip().lower()
    pwd   = d.get('pass') or ''
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_User, mdp FROM utilisateur WHERE email=%s', (email,))
            row = cur.fetchone()
            if not row or not check_password_hash(row['mdp'], pwd):
                return err('Email ou mot de passe incorrect.', 401)
            session['uid'] = row['id_User']
            session.pop('admin', None)
            return ok({'user': fetch_user(cur, row['id_User'])})
    finally:
        conn.close()


@app.post('/api/logout')
def api_logout():
    session.pop('uid', None)
    session.pop('admin', None)
    return ok()


@app.get('/api/me')
def api_me():
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            u = fetch_user(cur, uid)
            if not u:
                session.pop('uid', None)
                return err('Utilisateur introuvable.', 404)
            return ok({'user': u})
    finally:
        conn.close()


# ============================================================
#  MOT DE PASSE OUBLIÉ (vérification email + téléphone)
# ============================================================
@app.post('/api/forgot-password')
def api_forgot_password():
    """Réinitialisation par double vérification :
       l'utilisateur fournit email + téléphone enregistrés + nouveau mot de passe.
       Si les deux correspondent au même compte, le mot de passe est changé.
       Sinon, message générique pour ne pas révéler quel champ est faux."""
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip().lower()
    tel   = parse_tel(d.get('tel'))
    pwd   = d.get('new_pass') or ''

    if not email or tel is None:
        return err('Email et téléphone requis.')
    if len(pwd) < 6:
        return err('Le mot de passe doit faire au moins 6 caractères.')

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_User FROM utilisateur WHERE email=%s AND tel=%s', (email, tel))
            row = cur.fetchone()
            if not row:
                # Message générique : on ne dit pas si c'est l'email ou le tel qui est faux
                return err('Les informations fournies ne correspondent à aucun compte.', 404)

            cur.execute('UPDATE utilisateur SET mdp=%s WHERE id_User=%s',
                        (generate_password_hash(pwd), row['id_User']))
            conn.commit()
            return ok({'message': 'Mot de passe réinitialisé.'})
    finally:
        conn.close()


# ============================================================
#  CHANGEMENT DE MOT DE PASSE (depuis le profil)
# ============================================================
@app.post('/api/profile/password')
def api_change_password():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    old = d.get('old_pass') or ''
    new = d.get('new_pass') or ''
    if len(new) < 6:
        return err('Le nouveau mot de passe doit faire au moins 6 caractères.')

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT mdp FROM utilisateur WHERE id_User=%s', (uid,))
            row = cur.fetchone()
            if not row or not check_password_hash(row['mdp'], old):
                return err('Ancien mot de passe incorrect.', 401)
            cur.execute('UPDATE utilisateur SET mdp=%s WHERE id_User=%s',
                        (generate_password_hash(new), uid))
            conn.commit()
            return ok({'message': 'Mot de passe modifié.'})
    finally:
        conn.close()


# ============================================================
#  PROFIL
# ============================================================
@app.put('/api/profile')
def api_profile_update():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    prenom = (d.get('prenom') or '').strip()
    nom    = (d.get('nom')    or '').strip()
    email  = (d.get('email')  or '').strip().lower()
    fil    = (d.get('filiere') or '').strip()
    niv    = (d.get('niveau')  or '').strip()
    bio    = (d.get('bio')     or '').strip()
    tel    = parse_tel(d.get('tel'))

    if not (prenom and nom and email and fil and niv):
        return err('Champs obligatoires manquants.')
    if tel is None:
        return err('Le téléphone doit faire exactement 10 chiffres.')

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id_User FROM utilisateur
                           WHERE (email=%s OR tel=%s) AND id_User<>%s LIMIT 1""",
                        (email, tel, uid))
            if cur.fetchone():
                return err('Email ou téléphone déjà utilisé par un autre compte.')

            cur.execute('SELECT id_Fil FROM filiere WHERE lib_Fil=%s', (fil,))
            r = cur.fetchone()
            if not r: return err('Filière inconnue.')
            id_fil = r['id_Fil']
            cur.execute('SELECT id_Niv FROM niveau WHERE lib_Niv=%s', (niv,))
            r = cur.fetchone()
            if not r: return err('Niveau inconnu.')
            id_niv = r['id_Niv']

            cur.execute("""UPDATE utilisateur
                           SET nom=%s, prenom=%s, email=%s, tel=%s,
                               id_Fil=%s, id_Niv=%s, bio=%s
                           WHERE id_User=%s""",
                        (nom, prenom, email, tel, id_fil, id_niv, bio, uid))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


@app.post('/api/profile/photo')
def api_profile_photo():
    uid, e = require_login()
    if e: return e
    if 'photo' not in request.files:
        return err('Aucun fichier reçu.')
    f = request.files['photo']
    if not f or not f.filename:
        return err('Fichier vide.')
    if not allowed_image(f.filename):
        return err('Format non supporté.')

    import time as _t
    ext   = f.filename.rsplit('.', 1)[1].lower()
    fname = secure_filename(f'user_{uid}_{int(_t.time())}.{ext}')
    f.save(os.path.join(UPLOAD_FOLDER, fname))
    rel_path = f'uploads/{fname}'

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT photo FROM utilisateur WHERE id_User=%s', (uid,))
            row = cur.fetchone()
            if row and row['photo']:
                old = os.path.join(BASE_DIR, row['photo'])
                if os.path.isfile(old):
                    try: os.remove(old)
                    except OSError: pass
            cur.execute('UPDATE utilisateur SET photo=%s WHERE id_User=%s', (rel_path, uid))
            conn.commit()
        return ok({'photo': '/' + rel_path})
    finally:
        conn.close()


# ============================================================
#  COMPÉTENCES
# ============================================================
@app.post('/api/competences')
def api_comp_add():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    mat = (d.get('matiere') or '').strip()
    maitrise = bool(d.get('maitrise'))
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Mat FROM matiere WHERE lib_Mat=%s', (mat,))
            r = cur.fetchone()
            if not r: return err('Matière inconnue.')
            id_mat = r['id_Mat']

            cur.execute('SELECT maitrise FROM competence WHERE id_User=%s AND id_Mat=%s', (uid, id_mat))
            existing = cur.fetchone()
            if existing:
                if bool(existing['maitrise']) == maitrise:
                    return err('Cette matière est déjà dans la liste.')
                return err("Cette matière est dans l'autre catégorie. Retirez-la d'abord.")

            cur.execute('INSERT INTO competence (id_User, id_Mat, maitrise) VALUES (%s, %s, %s)',
                        (uid, id_mat, maitrise))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


@app.delete('/api/competences/<path:matiere>')
def api_comp_del(matiere):
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Mat FROM matiere WHERE lib_Mat=%s', (matiere,))
            r = cur.fetchone()
            if not r: return err('Matière inconnue.')
            cur.execute('DELETE FROM competence WHERE id_User=%s AND id_Mat=%s', (uid, r['id_Mat']))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


# ============================================================
#  DISPONIBILITÉS
# ============================================================
@app.post('/api/dispos')
def api_dispo_add():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    jour  = (d.get('jour')  or '').strip()
    debut = (d.get('debut') or '').strip()
    fin   = (d.get('fin')   or '').strip()

    if jour not in JOURS:
        return err('Jour invalide.')
    if not re.match(r'^\d{2}:\d{2}$', debut) or not re.match(r'^\d{2}:\d{2}$', fin):
        return err('Format des heures invalide.')
    if fin <= debut:
        return err("L'heure de fin doit être après l'heure de début.")

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO disponibilite (jour, heure_debut, heure_fin, id_User)
                           VALUES (%s, %s, %s, %s)""", (jour, debut, fin, uid))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


@app.delete('/api/dispos/<int:id_dispo>')
def api_dispo_del(id_dispo):
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM disponibilite WHERE id_Dispo=%s AND id_User=%s',
                        (id_dispo, uid))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


# ============================================================
#  ANNONCES
# ============================================================
@app.post('/api/annonces')
def api_annonce_add():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    type_   = (d.get('type')   or '').strip()
    fmt     = (d.get('format') or '').strip()
    mat     = (d.get('mat')    or '').strip()
    details = (d.get('details') or '').strip()

    if type_ not in ('Offre', 'Demande'):
        return err("Type invalide.")
    if fmt not in ('Présentiel', 'En ligne', 'Les deux'):
        return err("Format invalide.")
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Mat FROM matiere WHERE lib_Mat=%s', (mat,))
            r = cur.fetchone()
            if not r: return err('Matière inconnue.')
            cur.execute("""INSERT INTO annonce (type_annonce, format, details, id_User, id_Mat)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (type_, fmt, details, uid, r['id_Mat']))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


@app.delete('/api/annonces/<int:id_annonce>')
def api_annonce_del(id_annonce):
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM annonce WHERE id_Annonce=%s AND id_User=%s',
                        (id_annonce, uid))
            conn.commit()
            return ok({'user': fetch_user(cur, uid)})
    finally:
        conn.close()


# ============================================================
#  MESSAGERIE
# ============================================================
@app.get('/api/users')
def api_users():
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id_User AS id, u.prenom, u.nom, u.photo,
                       f.lib_Fil AS filiere, n.lib_Niv AS niveau
                FROM utilisateur u
                JOIN filiere f ON u.id_Fil = f.id_Fil
                JOIN niveau  n ON u.id_Niv = n.id_Niv
                WHERE u.id_User <> %s
                ORDER BY u.prenom, u.nom
            """, (uid,))
            users = []
            for r in cur.fetchall():
                r['photo'] = ('/' + r['photo']) if r['photo'] else None
                users.append(r)
        return ok({'users': users})
    finally:
        conn.close()


@app.get('/api/users/<int:uid_target>')
def api_user_profile(uid_target):
    """Voir le profil public d'un autre utilisateur (depuis la messagerie)."""
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            u = fetch_user_public(cur, uid_target)
            if not u: return err('Utilisateur introuvable.', 404)
            return ok({'user': u})
    finally:
        conn.close()


@app.get('/api/conversations')
def api_convs_list():
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id_Convers AS id,
                       CASE WHEN c.id_User1 = %s THEN c.id_User2 ELSE c.id_User1 END AS other_id
                FROM conversation c
                WHERE c.id_User1 = %s OR c.id_User2 = %s
            """, (uid, uid, uid))
            convs = cur.fetchall()
            out = []
            for c in convs:
                other = fetch_user_brief(cur, c['other_id'])
                if not other: continue
                cur.execute("""
                    SELECT contenu, date_envoie, id_Expedit FROM message
                    WHERE id_Convers = %s ORDER BY date_envoie DESC LIMIT 1
                """, (c['id'],))
                last = cur.fetchone()
                out.append({
                    'id': c['id'], 'other': other,
                    'last': ({
                        'contenu': last['contenu'],
                        'date':    last['date_envoie'].isoformat() if last['date_envoie'] else None,
                        'from_me': bool(last['id_Expedit'] == uid)
                    } if last else None)
                })
            out.sort(key=lambda x: (x['last']['date'] if (x['last'] and x['last']['date']) else ''),
                     reverse=True)
        return ok({'conversations': out})
    finally:
        conn.close()


@app.post('/api/conversations')
def api_conv_open():
    uid, e = require_login()
    if e: return e
    d = request.get_json(silent=True) or {}
    other_id = d.get('other_id')
    try: other_id = int(other_id)
    except (TypeError, ValueError): return err('Identifiant invalide.')
    if other_id == uid:
        return err("Impossible de discuter avec soi-même.")

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_Convers FROM conversation
                WHERE (id_User1=%s AND id_User2=%s) OR (id_User1=%s AND id_User2=%s)
                LIMIT 1
            """, (uid, other_id, other_id, uid))
            row = cur.fetchone()
            if row:
                cid = row['id_Convers']
            else:
                cur.execute('SELECT id_User FROM utilisateur WHERE id_User=%s', (other_id,))
                if not cur.fetchone(): return err('Utilisateur introuvable.')
                cur.execute('INSERT INTO conversation (id_User1, id_User2) VALUES (%s, %s)',
                            (uid, other_id))
                cid = cur.lastrowid
                conn.commit()
            other = fetch_user_brief(cur, other_id)
        return ok({'id': cid, 'other': other})
    finally:
        conn.close()


@app.get('/api/conversations/<int:cid>/messages')
def api_conv_messages(cid):
    uid, e = require_login()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_User1, id_User2 FROM conversation WHERE id_Convers=%s', (cid,))
            row = cur.fetchone()
            if not row or uid not in (row['id_User1'], row['id_User2']):
                return err('Accès refusé.', 403)

            cur.execute("""
                SELECT id_Mess AS id, id_Expedit, contenu, date_envoie FROM message
                WHERE id_Convers = %s ORDER BY date_envoie ASC
            """, (cid,))
            msgs = [{
                'id':       r['id'],
                'from_me':  r['id_Expedit'] == uid,
                'sender':   r['id_Expedit'],
                'contenu':  r['contenu'],
                'date':     r['date_envoie'].isoformat() if r['date_envoie'] else None,
            } for r in cur.fetchall()]
        return ok({'messages': msgs, 'convers_id': cid})
    finally:
        conn.close()


# ----- Socket.IO -----
def _user_in_conv(cur, uid, cid):
    cur.execute('SELECT id_User1, id_User2 FROM conversation WHERE id_Convers=%s', (cid,))
    row = cur.fetchone()
    return bool(row and uid in (row['id_User1'], row['id_User2']))


@socketio.on('join')
def on_join(data):
    uid = session.get('uid')
    if not uid: return
    try: cid = int(data.get('id_Convers'))
    except (TypeError, ValueError): return
    conn = db()
    try:
        with conn.cursor() as cur:
            if not _user_in_conv(cur, uid, cid): return
    finally:
        conn.close()
    join_room(str(cid))


@socketio.on('join_user')
def on_join_user(_data):
    """Chaque utilisateur connecté rejoint une "room personnelle"
       pour recevoir les notifications de nouveaux messages sur toutes les pages."""
    uid = session.get('uid')
    if uid:
        join_room(f'user_{uid}')


@socketio.on('send_message')
def on_send_message(data):
    uid = session.get('uid')
    if not uid: return
    try: cid = int(data.get('id_Convers'))
    except (TypeError, ValueError): return
    contenu = (data.get('contenu') or '').strip()
    if not contenu or len(contenu) > 4000: return

    conn = db()
    try:
        with conn.cursor() as cur:
            if not _user_in_conv(cur, uid, cid): return
            cur.execute("""INSERT INTO message (contenu, id_Convers, id_Expedit)
                           VALUES (%s, %s, %s)""", (contenu, cid, uid))
            msg_id = cur.lastrowid
            cur.execute('SELECT date_envoie FROM message WHERE id_Mess=%s', (msg_id,))
            saved = cur.fetchone()
            # Récupère le destinataire et les infos de l'expéditeur pour la notification
            cur.execute("""SELECT id_User1, id_User2 FROM conversation WHERE id_Convers=%s""", (cid,))
            convrow = cur.fetchone()
            other_id = convrow['id_User2'] if convrow['id_User1'] == uid else convrow['id_User1']
            sender_info = fetch_user_brief(cur, uid)
            conn.commit()
    finally:
        conn.close()

    iso_date = saved['date_envoie'].isoformat() if (saved and saved['date_envoie']) else datetime.utcnow().isoformat()
    payload = {
        'id':         msg_id,
        'id_Convers': cid,
        'sender':     uid,
        'contenu':    contenu,
        'date':       iso_date
    }
    # Diffusion dans la room de la conversation (pour ceux qui regardent)
    emit('receive_message', payload, room=str(cid))
    # Notification push à l'autre participant (sur sa room personnelle)
    if other_id and other_id != uid:
        notif = {
            'id_Convers': cid,
            'sender':     uid,
            'sender_name': f"{sender_info['prenom']} {sender_info['nom']}" if sender_info else 'Quelqu\'un',
            'sender_photo': sender_info['photo'] if sender_info else None,
            'contenu':    contenu,
            'date':       iso_date
        }
        emit('notify_message', notif, room=f'user_{other_id}')


# ============================================================
#  MATCHING — DUAL (mentors pour moi + personnes à mentorer)
# ============================================================
def _hhmm(t):
    if hasattr(t, 'total_seconds'):
        s = int(t.total_seconds())
        return f'{s // 3600:02d}:{(s % 3600) // 60:02d}'
    return str(t)[:5]


def _load_users_for_matching(cur, uids):
    if not uids: return {}
    ph = ','.join(['%s'] * len(uids))
    cur.execute(f"""
        SELECT u.id_User, u.nom, u.prenom, u.photo, u.bio, u.id_Fil, u.id_Niv,
               f.lib_Fil AS filiere, n.lib_Niv AS niveau
        FROM utilisateur u
        JOIN filiere f ON u.id_Fil = f.id_Fil
        JOIN niveau  n ON u.id_Niv = n.id_Niv
        WHERE u.id_User IN ({ph})
    """, tuple(uids))
    by_id = {}
    for r in cur.fetchall():
        r['photo']       = ('/' + r['photo']) if r['photo'] else None
        r['bio']         = r['bio'] or ''
        r['forts_ids']   = set()
        r['lacunes_ids'] = set()
        r['mat_names']   = {}
        r['forts']       = []
        r['dispos']      = []
        by_id[r['id_User']] = r

    cur.execute(f"""
        SELECT c.id_User, c.id_Mat, c.maitrise, m.lib_Mat
        FROM competence c JOIN matiere m ON c.id_Mat = m.id_Mat
        WHERE c.id_User IN ({ph})
    """, tuple(uids))
    for r in cur.fetchall():
        u = by_id.get(r['id_User'])
        if not u: continue
        u['mat_names'][r['id_Mat']] = r['lib_Mat']
        if r['maitrise']: u['forts_ids'].add(r['id_Mat'])
        else:             u['lacunes_ids'].add(r['id_Mat'])
    for u in by_id.values():
        u['forts'] = sorted({u['mat_names'][i] for i in u['forts_ids']})

    cur.execute(f"""
        SELECT id_User, jour, heure_debut, heure_fin FROM disponibilite
        WHERE id_User IN ({ph})
    """, tuple(uids))
    for r in cur.fetchall():
        u = by_id.get(r['id_User'])
        if not u: continue
        u['dispos'].append({
            'jour':  r['jour'],
            'debut': _hhmm(r['heure_debut']),
            'fin':   _hhmm(r['heure_fin']),
        })
    return by_id


def _compute_score(asker, helper):
    """Score de compatibilité quand 'asker' veut être aidé par 'helper'.
       - 50 pts : matières (lacunes d'asker couvertes par les forts de helper)
       - 30 pts : créneaux horaires communs
       - 20 pts : proximité académique (même filière + niveau)"""
    common = asker['lacunes_ids'] & helper['forts_ids']

    if asker['lacunes_ids']:
        s_mat = (len(common) / len(asker['lacunes_ids'])) * 50.0
    else:
        s_mat = 25.0

    creneaux = []
    seen = set()
    covered = set()
    for i, md in enumerate(asker['dispos']):
        for od in helper['dispos']:
            if md['jour'] != od['jour']: continue
            start = max(md['debut'], od['debut'])
            end   = min(md['fin'],   od['fin'])
            if start < end:
                covered.add(i)
                key = (md['jour'], start, end)
                if key not in seen:
                    seen.add(key)
                    creneaux.append({'jour': md['jour'], 'debut': start, 'fin': end})

    if asker['dispos']:
        s_disp = (len(covered) / len(asker['dispos'])) * 30.0
    else:
        s_disp = 15.0

    s_prox = 0
    if asker['id_Fil'] == helper['id_Fil']: s_prox += 10
    if asker['id_Niv'] == helper['id_Niv']: s_prox += 10

    return {
        'score':            round(s_mat + s_disp + s_prox, 1),
        'score_matieres':   round(s_mat, 1),
        'score_dispos':     round(s_disp, 1),
        'score_proximite':  s_prox,
        'matieres_ids':     common,
        'creneaux_communs': creneaux,
    }


def _build_mentor_row(other, sc):
    common_names = sorted(other['mat_names'][i] for i in sc['matieres_ids'])
    return {
        'id':                other['id_User'],
        'prenom':            other['prenom'],
        'nom':               other['nom'],
        'photo':             other['photo'],
        'bio':               other['bio'],
        'filiere':           other['filiere'],
        'niveau':            other['niveau'],
        'forts':             other['forts'],
        'score':             sc['score'],
        'score_matieres':    sc['score_matieres'],
        'score_dispos':      sc['score_dispos'],
        'score_proximite':   sc['score_proximite'],
        'matieres_communes': common_names,
        'creneaux_communs':  sc['creneaux_communs'],
    }


@app.get('/api/mentors')
def api_mentors():
    """Renvoie DEUX listes :
       - 'pour_moi'   : mentors qui peuvent m'aider (leurs forts ∩ mes lacunes)
       - 'a_mentorer' : personnes que je peux aider (mes forts ∩ leurs lacunes)"""
    uid, e = require_login()
    if e: return e

    q       = (request.args.get('q')       or '').strip().lower()
    filiere = (request.args.get('filiere') or '').strip()
    niveau  = (request.args.get('niveau')  or '').strip()
    matiere = (request.args.get('matiere') or '').strip()

    conn = db()
    try:
        with conn.cursor() as cur:
            me = _load_users_for_matching(cur, [uid]).get(uid)
            if not me:
                return err('Profil introuvable.', 404)

            sql = """
                SELECT u.id_User FROM utilisateur u
                JOIN filiere f ON u.id_Fil = f.id_Fil
                JOIN niveau  n ON u.id_Niv = n.id_Niv
                WHERE u.id_User <> %s
            """
            params = [uid]
            if filiere:
                sql += ' AND f.lib_Fil = %s'; params.append(filiere)
            if niveau:
                sql += ' AND n.lib_Niv = %s'; params.append(niveau)
            if q:
                sql += ' AND (LOWER(u.prenom) LIKE %s OR LOWER(u.nom) LIKE %s)'
                params.extend([f'%{q}%', f'%{q}%'])
            if matiere:
                sql += """ AND u.id_User IN (
                    SELECT c.id_User FROM competence c
                    JOIN matiere m ON c.id_Mat = m.id_Mat
                    WHERE m.lib_Mat = %s AND c.maitrise = TRUE
                )"""
                params.append(matiere)

            cur.execute(sql, tuple(params))
            cand_ids = [r['id_User'] for r in cur.fetchall()]
            if not cand_ids:
                return ok({'pour_moi': [], 'a_mentorer': []})

            all_data = _load_users_for_matching(cur, cand_ids)

            pour_moi = []     # Mentors qui peuvent m'aider
            a_mentorer = []   # Personnes que je peux aider

            for cid in cand_ids:
                other = all_data.get(cid)
                if not other: continue

                # POUR MOI : l'autre a des forts, on regarde si ça couvre mes lacunes
                if other['forts_ids']:
                    sc = _compute_score(me, other)
                    if sc['score'] > 0:
                        pour_moi.append(_build_mentor_row(other, sc))

                # A MENTORER : moi j'ai des forts, on regarde si ça couvre les lacunes de l'autre
                if me['forts_ids']:
                    sc_rev = _compute_score(other, me)
                    # On échange les noms de matières (du POV de l'autre)
                    common_for_other = other['lacunes_ids'] & me['forts_ids']
                    common_names = sorted(me['mat_names'][i] for i in common_for_other)
                    if sc_rev['score'] > 0 and common_for_other:
                        row = _build_mentor_row(other, sc_rev)
                        row['matieres_communes'] = common_names
                        a_mentorer.append(row)

            pour_moi.sort(key=lambda x: x['score'], reverse=True)
            a_mentorer.sort(key=lambda x: x['score'], reverse=True)

        return ok({'pour_moi': pour_moi, 'a_mentorer': a_mentorer})
    finally:
        conn.close()


# ============================================================
#  ADMINISTRATION
# ============================================================
@app.post('/api/admin/login')
def api_admin_login():
    """Connexion admin : nom + prénom + mot de passe partagé."""
    d = request.get_json(silent=True) or {}
    nom    = (d.get('nom')    or '').strip()
    prenom = (d.get('prenom') or '').strip()
    pwd    =  d.get('pass')   or ''

    if not (nom and prenom and pwd):
        return err('Tous les champs sont obligatoires.')
    if pwd != ADMIN_PASSWORD:
        return err('Mot de passe administrateur incorrect.', 401)

    # On enregistre dans la session
    session['admin']      = True
    session['admin_nom']  = nom
    session['admin_pren'] = prenom
    session.pop('uid', None)   # On ferme toute session utilisateur en cours
    return ok({'admin': {'nom': nom, 'prenom': prenom}})


@app.post('/api/admin/logout')
def api_admin_logout():
    session.pop('admin', None)
    session.pop('admin_nom', None)
    session.pop('admin_pren', None)
    return ok()


@app.get('/api/admin/me')
def api_admin_me():
    if not is_admin():
        return err('Non connecté en tant qu\'admin.', 401)
    return ok({'admin': {
        'nom': session.get('admin_nom', ''),
        'prenom': session.get('admin_pren', '')
    }})


@app.get('/api/admin/data')
def api_admin_data():
    """Renvoie toute la structure pour le dashboard admin :
       niveaux, filières, matières, et la matrice cours_matiere."""
    e = require_admin()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Niv AS id, lib_Niv AS lib FROM niveau ORDER BY id_Niv')
            niveaux = cur.fetchall()
            cur.execute('SELECT id_Fil AS id, lib_Fil AS lib FROM filiere ORDER BY lib_Fil')
            filieres = cur.fetchall()
            cur.execute('SELECT id_Mat AS id, lib_Mat AS lib FROM matiere ORDER BY lib_Mat')
            matieres = cur.fetchall()

            cur.execute('SELECT id_Cours, id_Fil, id_Niv FROM cours')
            cours = {(r['id_Fil'], r['id_Niv']): r['id_Cours'] for r in cur.fetchall()}

            cur.execute("""SELECT c.id_Fil, c.id_Niv, cm.id_Mat
                           FROM cours_matiere cm JOIN cours c ON cm.id_Cours = c.id_Cours""")
            # Structure : { "id_Fil_id_Niv": [id_Mat, ...] }
            programme = {}
            for r in cur.fetchall():
                key = f"{r['id_Fil']}_{r['id_Niv']}"
                programme.setdefault(key, []).append(r['id_Mat'])

            # Stats
            cur.execute('SELECT COUNT(*) AS n FROM utilisateur')
            nb_users = cur.fetchone()['n']
            cur.execute('SELECT COUNT(*) AS n FROM conversation')
            nb_convs = cur.fetchone()['n']
            cur.execute('SELECT COUNT(*) AS n FROM message')
            nb_msgs = cur.fetchone()['n']

        return ok({
            'niveaux': niveaux, 'filieres': filieres, 'matieres': matieres,
            'programme': programme,
            'stats': {'users': nb_users, 'conversations': nb_convs, 'messages': nb_msgs}
        })
    finally:
        conn.close()


@app.post('/api/admin/filieres')
def api_admin_add_filiere():
    e = require_admin()
    if e: return e
    d = request.get_json(silent=True) or {}
    lib = (d.get('lib') or '').strip()
    if not lib: return err('Libellé requis.')
    if len(lib) > 50: return err('Libellé trop long (max 50 caractères).')
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Fil FROM filiere WHERE lib_Fil=%s', (lib,))
            if cur.fetchone():
                return err('Cette filière existe déjà.')
            cur.execute('INSERT INTO filiere (lib_Fil) VALUES (%s)', (lib,))
            new_id = cur.lastrowid
            # On crée automatiquement un cours pour chaque niveau
            cur.execute('SELECT id_Niv FROM niveau')
            for r in cur.fetchall():
                cur.execute('INSERT INTO cours (lib_Cours, id_Fil, id_Niv) VALUES (%s, %s, %s)',
                            (lib, new_id, r['id_Niv']))
            conn.commit()
            return ok({'id': new_id})
    finally:
        conn.close()


@app.delete('/api/admin/filieres/<int:id_fil>')
def api_admin_del_filiere(id_fil):
    e = require_admin()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM utilisateur WHERE id_Fil=%s', (id_fil,))
            n = cur.fetchone()['n']
            if n > 0:
                return err(f'Impossible : {n} utilisateur(s) utilisent cette filière.')
            cur.execute('DELETE FROM filiere WHERE id_Fil=%s', (id_fil,))
            conn.commit()
            return ok()
    finally:
        conn.close()


@app.post('/api/admin/matieres')
def api_admin_add_matiere():
    e = require_admin()
    if e: return e
    d = request.get_json(silent=True) or {}
    lib = (d.get('lib') or '').strip()
    if not lib: return err('Libellé requis.')
    if len(lib) > 100: return err('Libellé trop long (max 100 caractères).')
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id_Mat FROM matiere WHERE lib_Mat=%s', (lib,))
            if cur.fetchone():
                return err('Cette matière existe déjà.')
            cur.execute('INSERT INTO matiere (lib_Mat) VALUES (%s)', (lib,))
            conn.commit()
            return ok({'id': cur.lastrowid})
    finally:
        conn.close()


@app.delete('/api/admin/matieres/<int:id_mat>')
def api_admin_del_matiere(id_mat):
    e = require_admin()
    if e: return e
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM competence WHERE id_Mat=%s', (id_mat,))
            n_comp = cur.fetchone()['n']
            cur.execute('SELECT COUNT(*) AS n FROM annonce WHERE id_Mat=%s', (id_mat,))
            n_ann = cur.fetchone()['n']
            if n_comp > 0 or n_ann > 0:
                return err(f'Impossible : matière utilisée par {n_comp} compétence(s) et {n_ann} annonce(s).')
            cur.execute('DELETE FROM matiere WHERE id_Mat=%s', (id_mat,))
            conn.commit()
            return ok()
    finally:
        conn.close()


@app.post('/api/admin/programme')
def api_admin_set_programme():
    """Définit la liste des matières pour un (filière, niveau) donné.
       Remplace toutes les associations existantes pour ce cours."""
    e = require_admin()
    if e: return e
    d = request.get_json(silent=True) or {}
    try:
        id_fil = int(d.get('id_Fil'))
        id_niv = int(d.get('id_Niv'))
    except (TypeError, ValueError):
        return err('id_Fil et id_Niv requis.')
    matieres_ids = d.get('matieres') or []
    if not isinstance(matieres_ids, list):
        return err('matieres doit être une liste d\'identifiants.')

    conn = db()
    try:
        with conn.cursor() as cur:
            # Trouve ou crée le cours pour ce (filière, niveau)
            cur.execute('SELECT id_Cours FROM cours WHERE id_Fil=%s AND id_Niv=%s', (id_fil, id_niv))
            row = cur.fetchone()
            if not row:
                cur.execute('SELECT lib_Fil FROM filiere WHERE id_Fil=%s', (id_fil,))
                f = cur.fetchone()
                if not f: return err('Filière introuvable.')
                cur.execute('INSERT INTO cours (lib_Cours, id_Fil, id_Niv) VALUES (%s, %s, %s)',
                            (f['lib_Fil'], id_fil, id_niv))
                id_cours = cur.lastrowid
            else:
                id_cours = row['id_Cours']

            # Supprime les associations existantes pour ce cours
            cur.execute('DELETE FROM cours_matiere WHERE id_Cours=%s', (id_cours,))
            # Ajoute les nouvelles
            for mid in matieres_ids:
                try: mid = int(mid)
                except (TypeError, ValueError): continue
                cur.execute('INSERT IGNORE INTO cours_matiere (id_Cours, id_Mat) VALUES (%s, %s)',
                            (id_cours, mid))
            conn.commit()
        return ok()
    finally:
        conn.close()


# ============================================================
#  LANCEMENT
# ============================================================
if __name__ == '__main__':
    print('─' * 60)
    print(f"Connexion MySQL : user='{DB_CONFIG['user']}' db='{DB_CONFIG['database']}'")
    try:
        _t = db(); _t.close()
        print('✓ Connexion MySQL OK')
    except pymysql.Error as e:
        print('✗ Connexion MySQL ÉCHEC :', e)
    print('─' * 60)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
