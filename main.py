# =============================================================
# Fichier : matching.py
# Projet  : IFRI_MentorLink — Groupe 65
# Rôle    : Algorithme de compatibilité et route de matching
# Auteur  :  AdjaïFlavia
# Branche : feature-matching
# =============================================================

from flask import request, jsonify
from flask_login import login_required, current_user


# =============================================================
# FONCTION PRINCIPALE : Calcul du score de compatibilité
# Score sur 100 points selon 3 critères du cahier des charges
# =============================================================

def calculer_score(utilisateur_connecte, autre_utilisateur):
    """
    Compare deux profils et retourne :
    - un score global sur 100
    - le détail des matières en commun
    - le détail des disponibilités communes

    Critères (cahier des charges page 6) :
    1. Compatibilité des compétences / matières   → 50 points max
    2. Compatibilité des horaires                 → 30 points max
    3. Proximité des filières et niveaux          → 20 points max
    """

    score = 0

    # ---------------------------------------------------------
    # CRITÈRE 1 : Compatibilité des matières (50 points max)
    #
    # Les lacunes de l'utilisateur connecté (maitrise=False)
    # doivent correspondre aux points forts de l'autre (maitrise=True)
    # ---------------------------------------------------------

    lacunes_connecte = set(
        c.id_Mat for c in utilisateur_connecte.competences if not c.maitrise
    )

    points_forts_autre = set(
        c.id_Mat for c in autre_utilisateur.competences if c.maitrise
    )

    matieres_communes = lacunes_connecte.intersection(points_forts_autre)

    if len(lacunes_connecte) > 0:
        score_matieres = (len(matieres_communes) / len(lacunes_connecte)) * 50
    else:
        score_matieres = 25  # score neutre si aucune lacune déclarée

    score += score_matieres

    # ---------------------------------------------------------
    # CRITÈRE 2 : Compatibilité des horaires (30 points max)
    #
    # Créneaux en commun entre les deux utilisateurs
    # Un créneau = (jour, heure_debut, heure_fin)
    # ---------------------------------------------------------

    dispos_connecte = set(
        (d.jour, str(d.heure_debut), str(d.heure_fin))
        for d in utilisateur_connecte.disponibilites
    )

    dispos_autre = set(
        (d.jour, str(d.heure_debut), str(d.heure_fin))
        for d in autre_utilisateur.disponibilites
    )

    creneaux_communs = dispos_connecte.intersection(dispos_autre)

    if len(dispos_connecte) > 0:
        score_dispos = (len(creneaux_communs) / len(dispos_connecte)) * 30
    else:
        score_dispos = 15  # score neutre si aucune dispo déclarée

    score += score_dispos

    # ---------------------------------------------------------
    # CRITÈRE 3 : Proximité filière et niveau (20 points max)
    #
    # Même filière = 10 pts → contexte académique similaire
    # Même niveau  = 10 pts → programme de cours identique
    # ---------------------------------------------------------

    score_proximite = 0

    if utilisateur_connecte.id_Fil == autre_utilisateur.id_Fil:
        score_proximite += 10

    if utilisateur_connecte.id_Niv == autre_utilisateur.id_Niv:
        score_proximite += 10

    score += score_proximite

    # Retourner le score ET les détails pour l'affichage (cahier des charges page 6)
    return {
        'score_total'      : round(score, 2),
        'score_matieres'   : round(score_matieres, 2),
        'score_dispos'     : round(score_dispos, 2),
        'score_proximite'  : score_proximite,
        'matieres_communes': list(matieres_communes),
        'creneaux_communs' : [
            {'jour': j, 'heure_debut': hd, 'heure_fin': hf}
            for j, hd, hf in creneaux_communs
        ],
    }


# =============================================================
# ROUTE 1 : GET /matching
# Retourne la liste de tous les utilisateurs triés par score
# Avec filtres optionnels depuis la page Mentors
# =============================================================

@app.route('/matching', methods=['GET'])
@login_required
def matching():
    """
    Route principale de matching.

    Paramètres optionnels dans l'URL :
    - id_Fil : filtrer par filière
    - id_Niv : filtrer par niveau
    - id_Mat : filtrer par matière spécifique

    Retourne une liste JSON triée par score décroissant.
    Chaque entrée contient les infos du cahier des charges (page 6) :
    - Nom et photo de profil
    - Compétences / matières en commun
    - Disponibilités communes
    - Score de compatibilité
    """

    # Utilisateur actuellement connecté
    utilisateur_connecte = Utilisateur.query.get(current_user.id_User)

    # Récupérer les filtres (tous optionnels)
    filtre_filiere = request.args.get('id_Fil', type=int)
    filtre_niveau  = request.args.get('id_Niv', type=int)
    filtre_matiere = request.args.get('id_Mat', type=int)

    # Tous les utilisateurs sauf soi-même
    query = Utilisateur.query.filter(
        Utilisateur.id_User != utilisateur_connecte.id_User
    )

    # Appliquer les filtres si fournis
    if filtre_filiere:
        query = query.filter(Utilisateur.id_Fil == filtre_filiere)

    if filtre_niveau:
        query = query.filter(Utilisateur.id_Niv == filtre_niveau)

    tous_utilisateurs = query.all()

    # Filtre par matière spécifique : garder ceux qui maîtrisent cette matière
    if filtre_matiere:
        tous_utilisateurs = [
            u for u in tous_utilisateurs
            if any(
                c.id_Mat == filtre_matiere and c.maitrise
                for c in u.competences
            )
        ]

    # Calculer le score pour chaque utilisateur
    resultats = []

    for utilisateur in tous_utilisateurs:

        details = calculer_score(utilisateur_connecte, utilisateur)

        # Ne pas afficher les utilisateurs avec un score de 0
        # (aucune compatibilité du tout)
        if details['score_total'] == 0:
            continue

        resultats.append({
            # Informations du profil (cahier des charges page 6)
            'id_User'          : utilisateur.id_User,
            'nom'              : utilisateur.nom,
            'prenom'           : utilisateur.prenom,
            'photo'            : utilisateur.photo,
            'bio'              : utilisateur.bio,
            'filiere'          : utilisateur.id_Fil,
            'niveau'           : utilisateur.id_Niv,

            # Score de compatibilité (cahier des charges page 6)
            'score'            : details['score_total'],
            'score_matieres'   : details['score_matieres'],
            'score_dispos'     : details['score_dispos'],
            'score_proximite'  : details['score_proximite'],

            # Détails pour l'affichage (cahier des charges page 6)
            'matieres_communes': details['matieres_communes'],
            'creneaux_communs' : details['creneaux_communs'],

            # Points forts de cet utilisateur (ce qu'il peut t'apporter)
            'points_forts'     : [
                c.id_Mat for c in utilisateur.competences if c.maitrise
            ],
        })

    # Trier du score le plus élevé au plus faible
    resultats.sort(key=lambda x: x['score'], reverse=True)

    return jsonify(resultats), 200


# =============================================================
# ROUTE 2 : GET /matching/detail/<id_user>
# Retourne le profil complet d'un utilisateur
# Pour afficher sa fiche complète quand on clique sur sa carte
# =============================================================

@app.route('/matching/detail/<int:id_user>', methods=['GET'])
@login_required
def detail_utilisateur(id_user):
    """
    Retourne toutes les informations d'un utilisateur
    ainsi que son score de compatibilité avec l'utilisateur connecté.
    """

    utilisateur_connecte = Utilisateur.query.get(current_user.id_User)
    utilisateur          = Utilisateur.query.get_or_404(id_user)

    details = calculer_score(utilisateur_connecte, utilisateur)

    return jsonify({
        # Infos profil
        'id_User'          : utilisateur.id_User,
        'nom'              : utilisateur.nom,
        'prenom'           : utilisateur.prenom,
        'email'            : utilisateur.email,
        'photo'            : utilisateur.photo,
        'bio'              : utilisateur.bio,
        'filiere'          : utilisateur.id_Fil,
        'niveau'           : utilisateur.id_Niv,

        # Compétences
        'points_forts'     : [
            c.id_Mat for c in utilisateur.competences if c.maitrise
        ],
        'lacunes'          : [
            c.id_Mat for c in utilisateur.competences if not c.maitrise
        ],

        # Disponibilités
        'disponibilites'   : [
            {
                'jour'       : d.jour,
                'heure_debut': str(d.heure_debut),
                'heure_fin'  : str(d.heure_fin)
            }
            for d in utilisateur.disponibilites
        ],

        # Score et détails de compatibilité
        'score'            : details['score_total'],
        'matieres_communes': details['matieres_communes'],
        'creneaux_communs' : details['creneaux_communs'],

    }), 200


# =============================================================
# ROUTE 3 : GET /matching/suggestions
# Propose automatiquement les meilleures suggestions
# sans que l'utilisateur ait à chercher lui-même
# =============================================================

@app.route('/matching/suggestions', methods=['GET'])
@login_required
def suggestions():
    """
    Retourne les 5 meilleurs profils compatibles
    pour affichage automatique sur le tableau de bord.
    """

    utilisateur_connecte = Utilisateur.query.get(current_user.id_User)

    tous_utilisateurs = Utilisateur.query.filter(
        Utilisateur.id_User != utilisateur_connecte.id_User
    ).all()

    resultats = []

    for utilisateur in tous_utilisateurs:
        details = calculer_score(utilisateur_connecte, utilisateur)

        if details['score_total'] == 0:
            continue

        resultats.append({
            'id_User' : utilisateur.id_User,
            'nom'     : utilisateur.nom,
            'prenom'  : utilisateur.prenom,
            'photo'   : utilisateur.photo,
            'score'   : details['score_total'],
            'matieres_communes': details['matieres_communes'],
        })

    resultats.sort(key=lambda x: x['score'], reverse=True)

    # Retourner seulement les 5 meilleurs
    return jsonify(resultats[:5]), 200
