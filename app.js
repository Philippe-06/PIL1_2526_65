/* ================================================================
   IFRI MentorLink — Front-end (app.js)
   ================================================================
   Auteur  : Groupe 65 (IFRI / UAC)
   Rôle    : Gestion de l'interface utilisateur et de la
             communication avec le serveur Flask.
   ================================================================ */

// ============================================================
// HELPERS GÉNÉRAUX
// ============================================================

// Raccourci pour document.getElementById
const $ = id => document.getElementById(id);

// Échappe les caractères HTML (anti-XSS)
const esc = s => (s || '').toString().replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));

// Toast classique (notif discrète en bas de l'écran)
let toastT;
function toast(msg) {
  const el = $('toast'); if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove('show'), 2800);
}

// Avatar : initiales
const initials = u => ((u && u.prenom ? u.prenom[0] : '?') + (u && u.nom ? u.nom[0] : '')).toUpperCase();
// Contenu interne d'un avatar : photo si dispo, sinon initiales
const avInner = u => u && u.photo ? ('<img src="' + esc(u.photo) + '">') : initials(u);
// Libellé d'une dispo : "Lundi 18:00-20:00"
const dispoLabel = d => !d ? '' : (esc(d.jour) + ' ' + esc(d.debut) + (d.fin ? '-' + esc(d.fin) : ''));

// Format de date "JJ/MM/AAAA HH:MM"
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return ('0'+d.getDate()).slice(-2)+'/'+('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear()
       +' '+('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);
}

// Format d'heure "HH:MM"
function fmtHour(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);
}

// Appel API JSON
async function api(url, options = {}) {
  options.headers = Object.assign({ 'Content-Type':'application/json' }, options.headers || {});
  options.credentials = 'same-origin';
  if (options.body && typeof options.body !== 'string') options.body = JSON.stringify(options.body);
  const r = await fetch(url, options);
  let data; try { data = await r.json(); } catch(e) { data = {}; }
  if (!r.ok || data.ok === false) throw new Error(data.error || ('Erreur ' + r.status));
  return data;
}

// ============================================================
// ÉTAT GLOBAL
// ============================================================

let ME = null;              // Utilisateur connecté
let SOCK = null;            // Socket.IO
let IS_ADMIN = false;       // Mode admin actif ?
let ADMIN_INFO = null;
let ADMIN_DATA = null;
let REFS = { filieres: [], niveaux: [], matieres: [] };

// Mentors : 2 listes séparées
let MENTORS_POUR_MOI = [];
let MENTORS_A_MENTORER = [];
let MT_TAB = 'pour-moi';
let MENTORS_LOADING = false;
let __mtDeb = null;

// Notification push
let CURRENT_NOTIF_CID = null;
let notifT = null;

// Messagerie
let CONVERSATIONS = [];
let active = null;
let currentMessages = [];

// Vue actuelle
let CURV = 'home';
const APPV  = ['dashboard','mentors','profil','messagerie'];
const AUTHV = ['login','signup','forgot','admin-login'];
const GATED = ['dashboard','mentors','messagerie'];


// ============================================================
// REVEAL ON SCROLL (Intersection Observer)
// ============================================================
let revealObs = null;
function setupRevealObserver() {
  if (!('IntersectionObserver' in window)) {
    // Fallback : tout visible
    document.querySelectorAll('.reveal').forEach(el => el.classList.add('in'));
    return;
  }
  revealObs = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        revealObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.05, rootMargin: '0px 0px -40px 0px' });
  document.querySelectorAll('.reveal').forEach(el => revealObs.observe(el));
}

// Quand on bascule de vue, certains éléments .reveal qui n'étaient
// pas observables (display:none parent) doivent être révélés s'ils
// sont à l'écran maintenant.
function refreshRevealForView(view) {
  const v = $('view-' + view); if (!v) return;
  setTimeout(() => {
    v.querySelectorAll('.reveal:not(.in)').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) {
        el.classList.add('in');
        if (revealObs) revealObs.unobserve(el);
      }
    });
  }, 60);
}


// ============================================================
// FAQ ACCORDION
// ============================================================
function setupFaqAccordion() {
  document.addEventListener('click', (e) => {
    const q = e.target.closest('.faq-q');
    if (!q) return;
    const item = q.closest('.faq-item');
    if (item) item.classList.toggle('active');
  });
}


// ============================================================
// SOCKET.IO
// ============================================================
function connectSocket() {
  if (SOCK) return SOCK;
  SOCK = io({ transports: ['websocket','polling'] });

  // À la connexion, on rejoint la room personnelle pour recevoir
  // les notifications de messages sur toutes les pages
  SOCK.on('connect', () => { SOCK.emit('join_user', {}); });

  // Message dans la conversation actuellement ouverte
  SOCK.on('receive_message', onIncomingMessage);

  // Notification push (autre conversation, ou page différente)
  SOCK.on('notify_message', onNotifyMessage);

  return SOCK;
}

function disconnectSocket() {
  if (SOCK) { try { SOCK.disconnect(); } catch(e){} SOCK = null; }
}


// ============================================================
// NOTIFICATIONS PUSH
// ============================================================
function onNotifyMessage(n) {
  // Si on est déjà dans la conversation concernée et sur la page
  // messagerie, pas besoin de notif : le message arrive en direct.
  if (CURV === 'messagerie' && active === n.id_Convers) return;
  showPushNotif(n);
}

function showPushNotif(n) {
  const el = $('notif-push'); if (!el) return;
  CURRENT_NOTIF_CID = n.id_Convers;
  const avatarHtml = n.sender_photo
    ? '<div class="av"><img src="'+esc(n.sender_photo)+'"></div>'
    : '<div class="av">'+esc((n.sender_name||'?').split(' ').map(s=>s[0]||'').join('').slice(0,2).toUpperCase())+'</div>';
  el.innerHTML = avatarHtml +
    '<div class="npbody">'+
      '<div class="npname">'+esc(n.sender_name||'Quelqu\'un')+'</div>'+
      '<div class="npmsg">'+esc(n.contenu||'')+'</div>'+
    '</div>';
  el.classList.add('show');
  clearTimeout(notifT);
  notifT = setTimeout(() => { el.classList.remove('show'); }, 5000);
}

function openNotif() {
  const cid = CURRENT_NOTIF_CID;
  const el = $('notif-push');
  if (el) el.classList.remove('show');
  clearTimeout(notifT);
  if (!cid) return;
  show('messagerie');
  setTimeout(() => openConvoById(cid), 100);
}


// ============================================================
// UTILITAIRES PROFIL
// ============================================================
function isProfileComplete(u) {
  return !!(u && (u.forts||[]).length && (u.lacunes||[]).length && (u.dispos||[]).length);
}

function renderOnboardBanner() {
  const el = $('onboard-banner'); if (!el) return;
  if (!ME || isProfileComplete(ME)) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  const miss = [];
  if (!(ME.forts||[]).length)   miss.push('au moins un point fort');
  if (!(ME.lacunes||[]).length) miss.push('au moins une lacune');
  if (!(ME.dispos||[]).length)  miss.push('vos disponibilités');
  el.innerHTML =
    '<div style="background:#fff7e0;border:1px solid #f1c40f;border-radius:12px;padding:14px 18px;margin-bottom:18px">'+
    '<b>Complétez votre profil :</b> il manque ' + esc(miss.join(', ')) +
    '. Sans cela, vous ne pourrez pas accéder à la page Mentors ni à la Messagerie.</div>';
}

function completion(u) {
  if (!u) return 0;
  // La bio est facultative → elle n'est PAS comptée dans le pourcentage
  const f = [u.tel, (u.forts||[]).length, (u.lacunes||[]).length, (u.dispos||[]).length, u.photo, u.filiere, u.niveau];
  return Math.round(f.filter(Boolean).length / f.length * 100);
}

function updateNavLocks() {
  const links = document.querySelectorAll('[data-go]');
  const locked = !ME || !isProfileComplete(ME);
  links.forEach(a => {
    const target = a.getAttribute('data-go');
    if (GATED.includes(target)) {
      if (locked) {
        a.classList.add('locked');
        a.setAttribute('title', 'Complétez votre profil pour y accéder');
      } else {
        a.classList.remove('locked');
        a.removeAttribute('title');
      }
    }
  });
}

function renderTop() {
  const el = $('nav-av');
  if (el) el.innerHTML = ME ? avInner(ME) : '··';
  updateNavLocks();
}


// ============================================================
// DASHBOARD
// ============================================================
function renderDashboard() {
  if (!ME) return;
  const name = $('dash-name'); if (name) name.textContent = ME.prenom || '';

  // Compteurs (4 stat-cards)
  const stMatch = $('st-match'); if (stMatch) stMatch.textContent = MENTORS_POUR_MOI.length || (ME.forts||[]).length;
  const stConv  = $('st-conv');  if (stConv)  stConv.textContent  = CONVERSATIONS.length;
  const stUnr   = $('st-unread');if (stUnr)   stUnr.textContent   = '0';
  const pct     = completion(ME);
  const stPct   = $('st-pct');   if (stPct)   stPct.textContent   = pct + '%';
  const bar     = $('dash-bar'); if (bar)     bar.style.width     = pct + '%';

  // Masquer le panneau "Complétez votre profil" quand on est à 100%
  const completePanel = $('dash-complete-panel');
  if (completePanel) completePanel.style.display = (pct >= 100) ? 'none' : '';

  // Mentors suggérés (top 3 de la liste "pour moi")
  const sug = $('dash-suggest');
  if (sug) {
    if (!MENTORS_POUR_MOI.length) {
      sug.innerHTML = '<p style="color:var(--muted);font-size:.9rem">Visitez la page Mentors pour voir vos suggestions.</p>';
    } else {
      sug.innerHTML = MENTORS_POUR_MOI.slice(0,3).map(m =>
        '<div class="post" style="cursor:pointer" data-action="contact-mentor" data-uid="'+m.id+'">'+
          '<div class="av">'+avInner(m)+'</div>'+
          '<div class="pbody">'+
            '<b>'+esc(m.prenom)+' '+esc(m.nom)+'</b>'+
            '<div class="meta">'+esc(m.filiere)+' · '+esc(m.niveau)+'</div>'+
            ((m.matieres_communes||[]).length ? '<p>Peut vous aider en : '+esc(m.matieres_communes.slice(0,3).join(', '))+'</p>' : '')+
          '</div>'+
          '<span class="ptype Offre">'+m.score+'%</span>'+
        '</div>'
      ).join('');
    }
  }

  // Messages récents (top 3 conversations)
  const msgs = $('dash-msgs');
  if (msgs) {
    if (!CONVERSATIONS.length) {
      msgs.innerHTML = '<p style="color:var(--muted);font-size:.9rem">Pas encore de conversation. Allez sur la page Mentors pour en commencer une.</p>';
    } else {
      msgs.innerHTML = CONVERSATIONS.slice(0,3).map(c =>
        '<div class="post" style="cursor:pointer" data-action="open-convo" data-cid="'+c.id+'">'+
          '<div class="av">'+avInner(c.other)+'</div>'+
          '<div class="pbody">'+
            '<b>'+esc(c.other.prenom)+' '+esc(c.other.nom)+'</b>'+
            (c.last ? '<p style="color:var(--muted);font-size:.86rem;margin:4px 0 0">'+(c.last.from_me?'Vous : ':'')+esc((c.last.contenu||'').slice(0,80))+'</p>' : '<p style="color:var(--muted-2);font-size:.82rem">Aucun message</p>')+
          '</div>'+
        '</div>'
      ).join('');
    }
  }
}


// ============================================================
// MENTORS — DEUX LISTES (Pour moi / À mentorer)
// ============================================================
function reloadMentors() {
  if (!ME) return;
  clearTimeout(__mtDeb);
  __mtDeb = setTimeout(loadMentors, 200);
}

async function loadMentors() {
  if (!ME) return;
  MENTORS_LOADING = true;
  renderMentors();
  try {
    const q       = ($('mt-q')   || {value:''}).value.trim();
    const filiere = ($('mt-fil') || {value:''}).value;
    const fmt     = ($('mt-fmt') || {value:''}).value;
    const params = new URLSearchParams();
    if (q)       params.set('q', q);
    if (filiere) params.set('filiere', filiere);
    // fmt n'est pas géré côté serveur pour le matching, on l'ignore
    const res = await api('/api/mentors?' + params.toString());
    MENTORS_POUR_MOI   = res.pour_moi   || [];
    MENTORS_A_MENTORER = res.a_mentorer || [];
  } catch(e) {
    toast(e.message);
    MENTORS_POUR_MOI = []; MENTORS_A_MENTORER = [];
  }
  MENTORS_LOADING = false;
  renderMentors();
}

function renderMentors() {
  const grid = $('mentor-grid'); if (!grid) return;

  const tabsHtml =
    '<div class="mt-tabs">'+
      '<button data-action="mt-tab" data-tab="pour-moi"'+(MT_TAB==='pour-moi'?' class="active"':'')+'>'+
        'Mentors pour moi<span class="tab-count">'+MENTORS_POUR_MOI.length+'</span>'+
      '</button>'+
      '<button data-action="mt-tab" data-tab="a-mentorer"'+(MT_TAB==='a-mentorer'?' class="active"':'')+'>'+
        'Personnes que je peux aider<span class="tab-count">'+MENTORS_A_MENTORER.length+'</span>'+
      '</button>'+
    '</div>';

  // Met à jour le compteur visible
  const list = (MT_TAB === 'pour-moi') ? MENTORS_POUR_MOI : MENTORS_A_MENTORER;
  const mtCount = $('mt-count');
  if (mtCount) mtCount.textContent = list.length;

  if (MENTORS_LOADING) {
    grid.innerHTML = tabsHtml + '<p style="color:var(--muted);grid-column:1/-1">Recherche en cours…</p>';
    return;
  }

  if (!list.length) {
    const msg = (MT_TAB === 'pour-moi')
      ? 'Aucun mentor ne correspond à vos critères. Essayez d\'élargir vos filtres ou complétez vos lacunes.'
      : 'Aucune personne à mentorer pour l\'instant. Ajoutez plus de points forts pour augmenter vos chances.';
    grid.innerHTML = tabsHtml + '<p style="color:var(--muted);grid-column:1/-1">'+msg+'</p>';
    return;
  }

  const cards = list.map(m => {
    const matCommunes = (m.matieres_communes||[]).map(x => '<span class="tg">'+esc(x)+'</span>').join(' ');
    const creneaux    = (m.creneaux_communs||[]).slice(0,3).map(c =>
      '<span class="tg">'+esc(c.jour)+' '+esc(c.debut)+'-'+esc(c.fin)+'</span>'
    ).join(' ');
    const labelMat   = (MT_TAB === 'pour-moi') ? 'Peut vous aider en' : 'Lacunes que vous pouvez couvrir';
    const actionLab  = (MT_TAB === 'pour-moi') ? 'Contacter ce mentor' : 'Proposer mon aide';
    return ''+
    '<div class="mentor-card">'+
      '<div class="m-head">'+
        '<div class="av">'+avInner(m)+'</div>'+
        '<div class="m-id">'+
          '<b>'+esc(m.prenom)+' '+esc(m.nom)+'</b>'+
          '<span>'+esc(m.filiere)+' · '+esc(m.niveau)+'</span>'+
        '</div>'+
        '<div class="m-score">'+m.score+'<small>/100</small></div>'+
      '</div>'+
      (m.bio ? '<p class="m-bio">'+esc(m.bio)+'</p>' : '')+
      (matCommunes ? '<div class="m-row"><span class="m-lab">'+labelMat+' :</span><div>'+matCommunes+'</div></div>' : '')+
      (creneaux    ? '<div class="m-row"><span class="m-lab">Créneaux communs :</span><div>'+creneaux+'</div></div>' : '')+
      '<div class="m-actions">'+
        '<button class="btn btn-primary btn-block" data-action="contact-mentor" data-uid="'+m.id+'">'+actionLab+'</button>'+
      '</div>'+
    '</div>';
  }).join('');

  grid.innerHTML = tabsHtml + cards;
}


// ============================================================
// PROFIL
// ============================================================
const TG = { forts:'tg-forts', lacunes:'tg-lacunes', dispos:'tg-dispos' };

function renderTags(grp) {
  const el = $(TG[grp]); if (!el || !ME) return;
  if (grp === 'dispos') {
    el.innerHTML = (ME.dispos||[]).map(d =>
      '<span class="tg">'+esc(dispoLabel(d))+
      ' <button data-action="del-tag" data-grp="dispos" data-id="'+d.id+'">×</button></span>'
    ).join('') || '<span style="color:var(--muted-2);font-size:.85rem">Aucune disponibilité</span>';
  } else {
    const arr = ME[grp] || [];
    el.innerHTML = arr.map(m =>
      '<span class="tg">'+esc(m)+
      ' <button data-action="del-tag" data-grp="'+grp+'" data-mat="'+esc(m)+'">×</button></span>'
    ).join('') || '<span style="color:var(--muted-2);font-size:.85rem">Aucune entrée</span>';
  }
}

function renderProfile() {
  if (!ME) return;
  const av = $('prof-avatar'); if (av) av.innerHTML = avInner(ME);
  const name = $('prof-name'); if (name) name.textContent = (ME.prenom||'') + ' ' + (ME.nom||'');
  const meta = $('prof-meta'); if (meta) meta.textContent = (ME.filiere||'') + ' · ' + (ME.niveau||'');

  if ($('pf-prenom'))  $('pf-prenom').value  = ME.prenom || '';
  if ($('pf-nom'))     $('pf-nom').value     = ME.nom    || '';
  if ($('pf-email'))   $('pf-email').value   = ME.email  || '';
  if ($('pf-tel'))     $('pf-tel').value     = ME.tel    || '';
  if ($('pf-filiere')) $('pf-filiere').value = ME.filiere|| '';
  if ($('pf-niveau'))  $('pf-niveau').value  = ME.niveau || '';
  if ($('pf-bio'))     $('pf-bio').value     = ME.bio    || '';

  refreshMatieresSelects();
  renderTags('forts');
  renderTags('lacunes');
  renderTags('dispos');

  const pct = completion(ME);
  const bar = $('pf-bar'), pctEl = $('pf-pct');
  if (bar) bar.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct;
}

// Met à jour les sélecteurs de matières (filtrés selon filière/niveau de l'utilisateur)
function refreshMatieresSelects() {
  const opts = '<option value="">— choisir une matière —</option>' +
               (REFS.matieres||[]).map(m => '<option>'+esc(m)+'</option>').join('');
  ['add-forts','add-lacunes','pb-mat'].forEach(id => { const el = $(id); if (el) el.innerHTML = opts; });
}

function pickPhoto() { const p = $('pf-photo'); if (p) p.click(); }

async function onPhoto(e) {
  const f = e.target.files && e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('photo', f);
  try {
    const r = await fetch('/api/profile/photo', { method:'POST', body: fd, credentials:'same-origin' });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'Échec');
    ME = Object.assign({}, ME, { photo: data.photo });
    renderProfile(); renderTop();
    toast('Photo mise à jour');
  } catch(e) { toast(e.message); }
}


// ============================================================
// ANNONCES (rendues sur la page Mentors dans #posts-list)
// ============================================================
function renderPosts() {
  const list = $('posts-list'); if (!list) return;
  const arr = (ME && ME.annonces) || [];
  if (!arr.length) {
    list.innerHTML = '<p style="color:var(--muted-2);font-size:.85rem">Aucune annonce. Cliquez sur « Publier une offre / demande » pour vous faire connaître.</p>';
    return;
  }
  list.innerHTML = arr.map(a =>
    '<div class="post">'+
      '<span class="ptype '+esc(a.type)+'">'+esc(a.type)+'</span>'+
      '<div class="pbody">'+
        '<b>'+esc(a.mat)+'</b>'+
        '<div class="meta">'+esc(a.format)+' · '+fmtDate(a.date_pub)+'</div>'+
        (a.details ? '<p>'+esc(a.details)+'</p>' : '')+
      '</div>'+
      '<button class="del" data-action="del-annonce" data-id="'+a.id+'" title="Supprimer">×</button>'+
    '</div>'
  ).join('');
}


// ============================================================
// MESSAGERIE
// ============================================================
async function loadConvos() {
  if (!ME) return;
  try {
    const res = await api('/api/conversations');
    CONVERSATIONS = res.conversations || [];
    renderConvoList();
  } catch(e) { toast(e.message); }
}

function renderConvoList() {
  const list = $('convo-list'); if (!list) return;
  if (!CONVERSATIONS.length) {
    list.innerHTML = '<p style="color:var(--muted);padding:14px;font-size:.85rem">Aucune conversation. Cliquez sur « + Nouvelle » ou utilisez la page Mentors.</p>';
    return;
  }
  list.innerHTML = CONVERSATIONS.map(c => {
    const isActive = (active === c.id) ? ' active' : '';
    const lastTxt = c.last ? (c.last.from_me ? 'Vous : ' : '') + (c.last.contenu||'') : '—';
    return '<div class="convo'+isActive+'" data-action="open-convo" data-cid="'+c.id+'">'+
      '<div class="av">'+avInner(c.other)+'</div>'+
      '<div class="cmeta">'+
        '<b>'+esc(c.other.prenom)+' '+esc(c.other.nom)+'</b>'+
        '<span class="lastmsg">'+esc(lastTxt.slice(0,60))+'</span>'+
      '</div>'+
      (c.last && c.last.date ? '<span class="ctime">'+fmtHour(c.last.date)+'</span>' : '')+
    '</div>';
  }).join('');
}

// Rend tout l'intérieur du thread : head + body + composer
function renderThread() {
  const th = $('thread'); if (!th) return;

  if (!active) {
    th.innerHTML = '<div class="thread-empty" style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);text-align:center;padding:40px">Sélectionnez une conversation à gauche.<br><span style="font-size:.85rem">Ou allez sur Mentors pour en commencer une.</span></div>';
    return;
  }

  const conv = CONVERSATIONS.find(c => c.id === active);
  if (!conv) { th.innerHTML = ''; return; }

  const headHtml =
    '<div class="thread-head">'+
      '<div class="av">'+avInner(conv.other)+'</div>'+
      '<div style="flex:1">'+
        '<b style="font-family:var(--ff-display);font-size:1rem">'+esc(conv.other.prenom)+' '+esc(conv.other.nom)+'</b>'+
        '<div class="stat-on"><i></i>'+esc(conv.other.filiere)+' · '+esc(conv.other.niveau)+'</div>'+
      '</div>'+
      '<button class="btn-viewprof" data-action="view-profile" data-uid="'+conv.other.id+'">Voir profil</button>'+
    '</div>';

  const bodyHtml = '<div class="thread-body" id="thread-body">' +
    (currentMessages.length
      ? currentMessages.map(m =>
          '<div class="bub '+(m.from_me ? 'me' : 'them')+'">'+esc(m.contenu)+
          '<span style="display:block;font-size:.7rem;opacity:.6;margin-top:4px">'+fmtHour(m.date)+'</span></div>'
        ).join('')
      : '<p style="color:var(--muted);text-align:center;margin:auto">Aucun message. Lancez la conversation 👋</p>'
    )+
    '</div>';

  const footHtml =
    '<div class="thread-foot">'+
      '<input id="msg-input" placeholder="Écrivez un message…" autocomplete="off">'+
      '<button class="btn btn-primary" data-action="send-msg">Envoyer</button>'+
    '</div>';

  th.innerHTML = headHtml + bodyHtml + footHtml;
  const body = $('thread-body');
  if (body) body.scrollTop = body.scrollHeight;
  const inp = $('msg-input'); if (inp) inp.focus();
}

async function openConvoById(cid) {
  if (!cid) return;
  if (!CONVERSATIONS.length) await loadConvos();
  active = cid;
  try {
    const res = await api('/api/conversations/'+cid+'/messages');
    currentMessages = res.messages || [];
  } catch(e) { toast(e.message); return; }
  if (SOCK) SOCK.emit('join', { id_Convers: cid });
  renderConvoList();
  renderThread();
}

async function openConvoWithUser(uid) {
  try {
    const res = await api('/api/conversations', { method:'POST', body:{ other_id: uid } });
    show('messagerie');
    setTimeout(() => openConvoById(res.id), 100);
  } catch(e) { toast(e.message); }
}

function sendMsg() {
  if (!SOCK || !active) return;
  const inp = $('msg-input'); if (!inp) return;
  const txt = inp.value.trim();
  if (!txt) return;
  SOCK.emit('send_message', { id_Convers: active, contenu: txt });
  inp.value = '';
}

function onIncomingMessage(payload) {
  if (!payload || payload.id_Convers !== active) { loadConvos(); return; }
  currentMessages.push({
    id: payload.id,
    sender: payload.sender,
    from_me: ME && payload.sender === ME.id_User,
    contenu: payload.contenu,
    date: payload.date,
  });
  renderThread();
  loadConvos();
}

// Modale "Nouvelle conversation" — liste tous les utilisateurs
async function openUsersPicker() {
  const ov = $('modal-users'); if (!ov) return;
  ov.classList.add('open');
  const ul = $('users-list');
  if (ul) ul.innerHTML = '<p style="color:var(--muted)">Chargement…</p>';
  try {
    const res = await api('/api/users');
    const users = res.users || [];
    if (!users.length) {
      if (ul) ul.innerHTML = '<p style="color:var(--muted)">Aucun autre utilisateur pour l\'instant.</p>';
      return;
    }
    if (ul) ul.innerHTML = users.map(u =>
      '<div class="convo" data-action="start-conv" data-uid="'+u.id+'" style="cursor:pointer">'+
        '<div class="av">'+avInner(u)+'</div>'+
        '<div class="cmeta">'+
          '<b>'+esc(u.prenom)+' '+esc(u.nom)+'</b>'+
          '<span class="lastmsg">'+esc(u.filiere||'')+' · '+esc(u.niveau||'')+'</span>'+
        '</div>'+
      '</div>'
    ).join('');
  } catch(e) {
    if (ul) ul.innerHTML = '<p style="color:#c0392b">'+esc(e.message)+'</p>';
  }
}

// ===== Voir le profil d'un autre utilisateur =====
async function viewUserProfile(uid) {
  if (!uid) return;
  const ov = $('modal-profview');
  const body = $('profview-body');
  if (!ov || !body) return;
  body.innerHTML = '<p style="color:var(--muted)">Chargement…</p>';
  ov.classList.add('open');
  try {
    const res = await api('/api/users/'+uid);
    const u = res.user;
    const fortsHtml   = (u.forts||[]).length   ? (u.forts||[]).map(x=>'<span class="tg">'+esc(x)+'</span>').join(' ')   : '<span style="color:var(--muted-2)">—</span>';
    const lacunesHtml = (u.lacunes||[]).length ? (u.lacunes||[]).map(x=>'<span class="tg">'+esc(x)+'</span>').join(' ') : '<span style="color:var(--muted-2)">—</span>';
    const disposHtml  = (u.dispos||[]).length
      ? '<p>' + (u.dispos||[]).map(d=>esc(dispoLabel(d))).join('<br>') + '</p>'
      : '<p style="color:var(--muted-2)">Aucune disponibilité indiquée</p>';
    const annonces    = (u.annonces||[]).slice(0,3);
    const annoncesHtml = annonces.length
      ? annonces.map(a=>'<p style="margin:4px 0;font-size:.88rem"><b>'+esc(a.type)+'</b> · '+esc(a.mat)+' ('+esc(a.format)+')'+(a.details?' — '+esc(a.details):'')+'</p>').join('')
      : '<p style="color:var(--muted-2);font-size:.88rem">Aucune annonce</p>';

    body.innerHTML =
      '<div class="pview-head">'+
        '<div class="av">'+avInner(u)+'</div>'+
        '<div class="info">'+
          '<b>'+esc(u.prenom)+' '+esc(u.nom)+'</b>'+
          '<span>'+esc(u.filiere)+' · '+esc(u.niveau)+'</span>'+
        '</div>'+
      '</div>'+
      (u.bio ? '<div class="pview-section"><h4>À propos</h4><p>'+esc(u.bio)+'</p></div>' : '')+
      '<div class="pview-section"><h4>Points forts</h4><div>'+fortsHtml+'</div></div>'+
      '<div class="pview-section"><h4>Lacunes</h4><div>'+lacunesHtml+'</div></div>'+
      '<div class="pview-section"><h4>Disponibilités</h4>'+disposHtml+'</div>'+
      '<div class="pview-section"><h4>Dernières annonces</h4>'+annoncesHtml+'</div>';
  } catch(e) {
    body.innerHTML = '<p style="color:#c0392b">'+esc(e.message)+'</p>';
  }
}

function closeProfView() { const ov = $('modal-profview'); if (ov) ov.classList.remove('open'); }


// ============================================================
// ADMINISTRATION
// ============================================================
async function adminLogin() {
  const errEl = $('ad-err'); if (errEl) errEl.textContent = '';
  const nom    = ($('ad-nom')   ||{value:''}).value.trim();
  const prenom = ($('ad-prenom')||{value:''}).value.trim();
  const pass   = ($('ad-pass')  ||{value:''}).value;
  if (!nom || !prenom || !pass) { if (errEl) errEl.textContent = 'Tous les champs sont obligatoires.'; return; }
  try {
    const res = await api('/api/admin/login', { method:'POST', body:{ nom, prenom, pass } });
    IS_ADMIN = true;
    ADMIN_INFO = res.admin;
    ME = null; disconnectSocket();
    show('admin');
    await loadAdminData();
  } catch(e) {
    if (errEl) errEl.textContent = e.message;
  }
}

async function adminLogout() {
  try { await api('/api/admin/logout', { method:'POST' }); } catch(e) {}
  IS_ADMIN = false; ADMIN_INFO = null; ADMIN_DATA = null;
  show('home');
}

async function loadAdminData() {
  try {
    ADMIN_DATA = await api('/api/admin/data');
    renderAdmin();
  } catch(e) { toast(e.message); }
}

function renderAdmin() {
  if (!ADMIN_DATA) return;
  if (ADMIN_INFO) {
    const g = $('admin-greeting');
    if (g) g.textContent = 'Connecté en tant que ' + ADMIN_INFO.prenom + ' ' + ADMIN_INFO.nom;
  }
  const stats = ADMIN_DATA.stats || {};
  const sEl = $('admin-stats');
  if (sEl) {
    sEl.innerHTML =
      '<div class="admin-stat"><div class="lab">Utilisateurs</div><div class="val">'+(stats.users||0)+'</div></div>'+
      '<div class="admin-stat"><div class="lab">Conversations</div><div class="val">'+(stats.conversations||0)+'</div></div>'+
      '<div class="admin-stat"><div class="lab">Messages</div><div class="val">'+(stats.messages||0)+'</div></div>'+
      '<div class="admin-stat"><div class="lab">Filières</div><div class="val">'+(ADMIN_DATA.filieres||[]).length+'</div></div>'+
      '<div class="admin-stat"><div class="lab">Matières</div><div class="val">'+(ADMIN_DATA.matieres||[]).length+'</div></div>';
  }
  const fLst = $('adm-fil-list');
  if (fLst) {
    fLst.innerHTML = (ADMIN_DATA.filieres||[]).map(f =>
      '<li><span>'+esc(f.lib)+'</span><button class="del" data-action="adm-del-fil" data-id="'+f.id+'" data-lib="'+esc(f.lib)+'" title="Supprimer">×</button></li>'
    ).join('');
    const fc = $('adm-fil-count'); if (fc) fc.textContent = (ADMIN_DATA.filieres||[]).length;
  }
  const mLst = $('adm-mat-list');
  if (mLst) {
    mLst.innerHTML = (ADMIN_DATA.matieres||[]).map(m =>
      '<li><span>'+esc(m.lib)+'</span><button class="del" data-action="adm-del-mat" data-id="'+m.id+'" data-lib="'+esc(m.lib)+'" title="Supprimer">×</button></li>'
    ).join('');
    const mc = $('adm-mat-count'); if (mc) mc.textContent = (ADMIN_DATA.matieres||[]).length;
  }
  const pFil = $('adm-prog-fil'), pNiv = $('adm-prog-niv');
  if (pFil) pFil.innerHTML = '<option value="">— Filière —</option>' +
    (ADMIN_DATA.filieres||[]).map(f=>'<option value="'+f.id+'">'+esc(f.lib)+'</option>').join('');
  if (pNiv) pNiv.innerHTML = '<option value="">— Niveau —</option>' +
    (ADMIN_DATA.niveaux||[]).map(n=>'<option value="'+n.id+'">'+esc(n.lib)+'</option>').join('');
  renderProgrammeMatieres();
}

function renderProgrammeMatieres() {
  const cont = $('adm-prog-mats'); if (!cont || !ADMIN_DATA) return;
  const fId = parseInt(($('adm-prog-fil')||{value:''}).value, 10);
  const nId = parseInt(($('adm-prog-niv')||{value:''}).value, 10);
  if (!fId || !nId) {
    cont.innerHTML = '<p style="color:var(--muted);font-size:.88rem;margin:0;grid-column:1/-1">Sélectionnez une filière et un niveau pour afficher les matières.</p>';
    return;
  }
  const key = fId + '_' + nId;
  const enabled = new Set((ADMIN_DATA.programme||{})[key] || []);
  cont.innerHTML = (ADMIN_DATA.matieres||[]).map(m =>
    '<label><input type="checkbox" value="'+m.id+'"'+(enabled.has(m.id)?' checked':'')+'>'+esc(m.lib)+'</label>'
  ).join('');
}

async function admAddFiliere() {
  const inp = $('adm-fil-input'); if (!inp) return;
  const lib = inp.value.trim();
  if (!lib) { toast('Saisissez un nom de filière'); return; }
  try { await api('/api/admin/filieres', { method:'POST', body:{ lib } }); inp.value=''; toast('Filière ajoutée'); await loadAdminData(); }
  catch(e) { toast(e.message); }
}

async function admDelFiliere(id, lib) {
  if (!confirm('Supprimer la filière « '+lib+' » ?\n(Impossible si elle est utilisée par des utilisateurs.)')) return;
  try { await api('/api/admin/filieres/'+id, { method:'DELETE' }); toast('Filière supprimée'); await loadAdminData(); }
  catch(e) { toast(e.message); }
}

async function admAddMatiere() {
  const inp = $('adm-mat-input'); if (!inp) return;
  const lib = inp.value.trim();
  if (!lib) { toast('Saisissez un nom de matière'); return; }
  try { await api('/api/admin/matieres', { method:'POST', body:{ lib } }); inp.value=''; toast('Matière ajoutée'); await loadAdminData(); }
  catch(e) { toast(e.message); }
}

async function admDelMatiere(id, lib) {
  if (!confirm('Supprimer la matière « '+lib+' » ?\n(Impossible si elle est utilisée dans des compétences ou annonces.)')) return;
  try { await api('/api/admin/matieres/'+id, { method:'DELETE' }); toast('Matière supprimée'); await loadAdminData(); }
  catch(e) { toast(e.message); }
}

async function admSaveProgramme() {
  const fId = parseInt(($('adm-prog-fil')||{value:''}).value, 10);
  const nId = parseInt(($('adm-prog-niv')||{value:''}).value, 10);
  if (!fId || !nId) { toast('Sélectionnez une filière et un niveau.'); return; }
  const checked = Array.from(document.querySelectorAll('#adm-prog-mats input[type=checkbox]:checked'))
    .map(c => parseInt(c.value, 10));
  try {
    await api('/api/admin/programme', { method:'POST', body:{ id_Fil:fId, id_Niv:nId, matieres:checked } });
    toast('Programme enregistré ('+checked.length+' matière'+(checked.length>1?'s':'')+')');
    await loadAdminData();
  } catch(e) { toast(e.message); }
}


// ============================================================
// AUTHENTIFICATION
// ============================================================
async function doLogin() {
  const errEl = $('li-err'); if (errEl) errEl.textContent = '';
  const email = ($('li-email')||{value:''}).value.trim();
  const pass  = ($('li-pass') ||{value:''}).value;
  try {
    const res = await api('/api/login', { method:'POST', body:{ email, pass } });
    ME = res.user;
    // Recharger /api/me pour avoir le profil complet (forts, lacunes, dispos)
    // et les refs filtrées selon la filière/niveau de l'utilisateur
    const [me2] = await Promise.all([api('/api/me'), loadRefs()]);
    ME = me2.user;
    connectSocket();
    await loadConvos();
    // Mettre à jour avatar + verrous AVANT de naviguer
    renderTop();
    show(isProfileComplete(ME) ? 'dashboard' : 'profil');
    toast('Bienvenue ' + (ME.prenom||''));
  } catch(e) { if (errEl) errEl.textContent = e.message; }
}

async function doSignup() {
  const errEl = $('su-err'); if (errEl) errEl.textContent = '';
  const body = {
    prenom:  ($('su-prenom')||{value:''}).value.trim(),
    nom:     ($('su-nom')   ||{value:''}).value.trim(),
    tel:     ($('su-tel')   ||{value:''}).value.trim(),
    email:   ($('su-email') ||{value:''}).value.trim(),
    pass:    ($('su-pass')  ||{value:''}).value,
    filiere: ($('su-fil')   ||{value:''}).value,
    niveau:  ($('su-niv')   ||{value:''}).value,
  };
  try {
    const res = await api('/api/signup', { method:'POST', body });
    ME = res.user;
    await loadRefs();
    connectSocket();
    show('profil');
    toast('Compte créé. Complétez votre profil.');
  } catch(e) { if (errEl) errEl.textContent = e.message; }
}

async function doLogout() {
  try { await api('/api/logout', { method:'POST' }); } catch(e) {}
  ME = null;
  CONVERSATIONS = []; active = null; currentMessages = [];
  MENTORS_POUR_MOI = []; MENTORS_A_MENTORER = [];
  disconnectSocket();
  show('home');
}

async function doForgotPassword() {
  const errEl = $('fg-err'); if (errEl) errEl.textContent = '';
  const email    = ($('fg-email')||{value:''}).value.trim();
  const tel      = ($('fg-tel')  ||{value:''}).value.trim();
  const new_pass = ($('fg-new')  ||{value:''}).value;
  if (!email || !tel || !new_pass) { if (errEl) errEl.textContent = 'Tous les champs sont obligatoires.'; return; }
  try {
    await api('/api/forgot-password', { method:'POST', body:{ email, tel, new_pass } });
    toast('Mot de passe réinitialisé. Connectez-vous.');
    setTimeout(() => show('login'), 800);
  } catch(e) { if (errEl) errEl.textContent = e.message; }
}

async function doChangePassword() {
  const errEl = $('pf-pwd-err'); if (errEl) errEl.textContent = '';
  const oldP = ($('pf-old-pwd')    ||{value:''}).value;
  const newP = ($('pf-new-pwd')    ||{value:''}).value;
  const conf = ($('pf-confirm-pwd')||{value:''}).value;
  if (!oldP || !newP) { if (errEl) errEl.textContent = 'Tous les champs sont obligatoires.'; return; }
  if (newP.length < 6) { if (errEl) errEl.textContent = 'Le nouveau mot de passe doit faire au moins 6 caractères.'; return; }
  if (newP !== conf)   { if (errEl) errEl.textContent = 'La confirmation ne correspond pas au nouveau mot de passe.'; return; }
  try {
    await api('/api/profile/password', { method:'POST', body:{ old_pass: oldP, new_pass: newP } });
    $('pf-old-pwd').value=''; $('pf-new-pwd').value=''; $('pf-confirm-pwd').value='';
    toast('Mot de passe modifié.');
  } catch(e) { if (errEl) errEl.textContent = e.message; }
}

async function saveProfile() {
  if (!ME) return;
  const body = {
    prenom:  ($('pf-prenom') ||{value:''}).value.trim(),
    nom:     ($('pf-nom')    ||{value:''}).value.trim(),
    email:   ($('pf-email')  ||{value:''}).value.trim(),
    tel:     ($('pf-tel')    ||{value:''}).value.trim(),
    filiere: ($('pf-filiere')||{value:''}).value,
    niveau:  ($('pf-niveau') ||{value:''}).value,
    bio:     ($('pf-bio')    ||{value:''}).value,
  };
  try {
    const res = await api('/api/profile', { method:'PUT', body });
    ME = res.user;
    await loadRefs();
    renderProfile(); renderTop(); renderOnboardBanner();
    toast('Profil enregistré');
  } catch(e) { toast(e.message); }
}

async function loadRefs() {
  try {
    const res = await api('/api/refs');
    REFS = { filieres: res.filieres||[], niveaux: res.niveaux||[], matieres: res.matieres||[] };
    refreshMatieresSelects();
  } catch(e) { /* silencieux */ }
}


// ============================================================
// TAGS : ajouter / supprimer
// ============================================================
async function addTag(grp) {
  if (!ME) return;
  if (grp === 'dispos') {
    const jour  = ($('add-d-jour')||{value:''}).value;
    const debut = ($('add-d-deb') ||{value:''}).value;
    const fin   = ($('add-d-fin') ||{value:''}).value;
    if (!jour) { toast('Choisissez un jour'); return; }
    try {
      const res = await api('/api/dispos', { method:'POST', body:{ jour, debut, fin } });
      ME = res.user;
      renderProfile(); renderTop(); renderOnboardBanner();
    } catch(e) { toast(e.message); }
  } else {
    const sel = $('add-'+grp); if (!sel) return;
    const mat = sel.value;
    if (!mat) { toast('Choisissez une matière'); return; }
    try {
      const res = await api('/api/competences', { method:'POST', body:{ matiere: mat, maitrise: (grp==='forts') } });
      ME = res.user;
      sel.value = '';
      renderProfile(); renderTop(); renderOnboardBanner();
    } catch(e) { toast(e.message); }
  }
}

async function delTag(grp, ref) {
  if (!ME) return;
  try {
    let res;
    if (grp === 'dispos') res = await api('/api/dispos/'+ref, { method:'DELETE' });
    else                  res = await api('/api/competences/'+encodeURIComponent(ref), { method:'DELETE' });
    ME = res.user;
    renderProfile(); renderTop(); renderOnboardBanner();
  } catch(e) { toast(e.message); }
}

async function delAnnonce(id) {
  if (!confirm('Supprimer cette annonce ?')) return;
  try {
    const res = await api('/api/annonces/'+id, { method:'DELETE' });
    ME = res.user;
    renderPosts();
  } catch(e) { toast(e.message); }
}

async function publishAnnonce() {
  const errEl = $('pb-err'); if (errEl) errEl.textContent = '';
  const typeRadio = document.querySelector('input[name="ptype"]:checked');
  const body = {
    type:    typeRadio ? typeRadio.value : 'Offre',
    format:  ($('pb-fmt')||{value:''}).value,
    mat:     ($('pb-mat')||{value:''}).value,
    details: ($('pb-desc')||{value:''}).value.trim(),
  };
  if (!body.type || !body.format || !body.mat) {
    if (errEl) errEl.textContent = 'Champs obligatoires manquants.';
    return;
  }
  try {
    const res = await api('/api/annonces', { method:'POST', body });
    ME = res.user;
    closeModal();
    renderPosts();
    if ($('pb-desc')) $('pb-desc').value = '';
    toast('Annonce publiée');
  } catch(e) { if (errEl) errEl.textContent = e.message; }
}


// ============================================================
// MODALES
// ============================================================
function openPubModal() {
  refreshMatieresSelects();
  const ov = $('modal-pub'); if (ov) ov.classList.add('open');
}
function closeModal()      { const ov=$('modal-pub');     if (ov) ov.classList.remove('open'); }
function closeUsersModal() { const ov=$('modal-users');   if (ov) ov.classList.remove('open'); }


// ============================================================
// NAVIGATION / ROUTING
// ============================================================
function closeDrawers() {
  ['drawer-public','drawer-app'].forEach(id => { const d = $(id); if (d) d.classList.remove('open'); });
  const sc = $('scrim'); if (sc) sc.classList.remove('open');
  document.querySelectorAll('.hamburger').forEach(h => h.classList.remove('open'));
  document.body.style.overflow = '';
}

function show(view, scrollTo) {
  if (APPV.includes(view) && !ME)         view = 'login';
  if (view === 'admin' && !IS_ADMIN)      view = 'admin-login';

  CURV = view;
  closeDrawers();

  document.querySelectorAll('main section.view').forEach(s => s.style.display = 'none');
  const v = $('view-' + view); if (v) v.style.display = 'block';

  const isApp     = APPV.includes(view) && ME;
  const isAdmPage = (view === 'admin' || view === 'admin-login');
  const np = $('nav-public'), na = $('nav-app'), ft = $('site-footer');
  if (np) np.style.display = (isApp || isAdmPage) ? 'none' : '';
  if (na) na.style.display = isApp ? '' : 'none';
  if (ft) ft.style.display = isAdmPage ? 'none' : '';

  document.querySelectorAll('.app-links a').forEach(a => {
    a.classList.toggle('active', a.getAttribute('data-go') === view);
  });
  // Mettre à jour les verrous à chaque navigation
  updateNavLocks();

  // Render spécifique
  if (view === 'dashboard') { renderDashboard(); }
  if (view === 'profil')    { renderProfile(); renderOnboardBanner(); }
  if (view === 'mentors')   { renderPosts(); reloadMentors(); }
  if (view === 'messagerie'){ loadConvos(); renderThread(); }
  if (view === 'admin' && IS_ADMIN && !ADMIN_DATA) loadAdminData();

  if (scrollTo) {
    setTimeout(() => {
      const el = document.getElementById(scrollTo);
      if (el) el.scrollIntoView({ behavior:'smooth', block:'start' });
    }, 100);
  } else {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  refreshRevealForView(view);
}


// ============================================================
// HANDLER GLOBAL DES CLICS
// ============================================================
document.addEventListener('click', async (e) => {
  // Navigation
  const goEl = e.target.closest('[data-go]');
  if (goEl) {
    e.preventDefault();
    const target = goEl.getAttribute('data-go');
    if (GATED.includes(target) && (!ME || !isProfileComplete(ME))) {
      toast('Complétez votre profil pour y accéder.');
      if (ME) show('profil'); else show('login');
      return;
    }
    show(target, goEl.getAttribute('data-scroll'));
    return;
  }

  // Hamburgers
  const hb = e.target.closest('[data-drawer]');
  if (hb) {
    e.preventDefault();
    const which = hb.getAttribute('data-drawer');
    const d = (which === 'app') ? $('drawer-app') : $('drawer-public');
    const sc = $('scrim');
    if (d) d.classList.toggle('open');
    if (sc) sc.classList.toggle('open');
    hb.classList.toggle('open');
    document.body.style.overflow = (d && d.classList.contains('open')) ? 'hidden' : '';
    return;
  }
  if (e.target === $('scrim')) { closeDrawers(); return; }

  // Actions data-action
  const act = e.target.closest('[data-action]');
  if (!act) return;
  const action = act.getAttribute('data-action');
  e.preventDefault();

  switch (action) {
    // ─── Auth ───
    case 'login':         return doLogin();
    case 'signup':        return doSignup();
    case 'logout':        return doLogout();
    case 'forgot-submit': return doForgotPassword();

    // ─── Œil mdp ───
    case 'toggle-pwd': {
      const target = act.getAttribute('data-target');
      const inp = $(target); if (!inp) return;
      inp.type = (inp.type === 'password') ? 'text' : 'password';
      return;
    }

    // ─── Profil ───
    case 'save-profile':  return saveProfile();
    case 'change-pwd':    return doChangePassword();
    case 'pick-photo':    return pickPhoto();
    case 'add-tag':       return addTag(act.getAttribute('data-grp'));
    case 'del-tag': {
      const grp = act.getAttribute('data-grp');
      const ref = (grp === 'dispos') ? act.getAttribute('data-id') : act.getAttribute('data-mat');
      return delTag(grp, ref);
    }

    // ─── Annonces ───
    case 'open-pub':     return openPubModal();
    case 'submit-pub':   return publishAnnonce();
    case 'del-annonce':  return delAnnonce(act.getAttribute('data-id'));
    case 'close-modal':  return closeModal();
    case 'close-users':  return closeUsersModal();

    // ─── Mentors ───
    case 'search-mentors': return reloadMentors();
    case 'mt-tab': {
      MT_TAB = act.getAttribute('data-tab') || 'pour-moi';
      renderMentors();
      return;
    }
    case 'contact-mentor': {
      const uid = parseInt(act.getAttribute('data-uid'), 10);
      return openConvoWithUser(uid);
    }

    // ─── Messagerie ───
    case 'open-convo': {
      const cid = parseInt(act.getAttribute('data-cid'), 10);
      return openConvoById(cid);
    }
    case 'send-msg':    return sendMsg();
    case 'new-conv':    return openUsersPicker();
    case 'start-conv': {
      const uid = parseInt(act.getAttribute('data-uid'), 10);
      closeUsersModal();
      return openConvoWithUser(uid);
    }
    case 'view-profile': {
      const uid = parseInt(act.getAttribute('data-uid'), 10);
      return viewUserProfile(uid);
    }
    case 'close-profview': return closeProfView();

    // ─── Notification push ───
    case 'open-notif': return openNotif();

    // ─── Admin ───
    case 'admin-login':  return adminLogin();
    case 'admin-logout': return adminLogout();
    case 'adm-add-fil':  return admAddFiliere();
    case 'adm-add-mat':  return admAddMatiere();
    case 'adm-del-fil':  return admDelFiliere(act.getAttribute('data-id'), act.getAttribute('data-lib'));
    case 'adm-del-mat':  return admDelMatiere(act.getAttribute('data-id'), act.getAttribute('data-lib'));
    case 'adm-save-prog':return admSaveProgramme();
  }
});


// ============================================================
// AUTRES ÉVÉNEMENTS
// ============================================================

// Envoi de message via Entrée
document.addEventListener('keydown', (e) => {
  if (e.target && e.target.id === 'msg-input' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault(); sendMsg();
  }
  if (e.key === 'Escape') { closeModal(); closeUsersModal(); closeProfView(); }
});

// Filtres mentors
['mt-q','mt-fil','mt-fmt'].forEach(id => {
  const el = $(id);
  if (el) {
    el.addEventListener('input', reloadMentors);
    el.addEventListener('change', reloadMentors);
  }
});

// Programme admin : re-render au changement
['adm-prog-fil','adm-prog-niv'].forEach(id => {
  const el = $(id);
  if (el) el.addEventListener('change', renderProgrammeMatieres);
});

// Photo de profil
document.addEventListener('change', (e) => {
  if (e.target && e.target.id === 'pf-photo') onPhoto(e);
});


// ============================================================
// DÉMARRAGE
// ============================================================
(async function boot() {
  // Setup .reveal observer + FAQ accordion AVANT toute navigation
  setupRevealObserver();
  setupFaqAccordion();

  await loadRefs();

  // Tente reprise session utilisateur
  try {
    const res = await api('/api/me');
    ME = res.user;
    await loadRefs();
    connectSocket();
    await loadConvos();
    renderTop(); // déverrouille les liens nav avant navigation
    show(isProfileComplete(ME) ? 'dashboard' : 'profil');
  } catch(e) {
    // Tente session admin
    try {
      const res = await api('/api/admin/me');
      IS_ADMIN = true;
      ADMIN_INFO = res.admin;
      show('admin');
      loadAdminData();
    } catch(e2) {
      show('home');
    }
  }

  renderTop();
})();
