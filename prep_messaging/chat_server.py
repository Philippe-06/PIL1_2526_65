
# ==============================================================================
# PROJET : IFRI MentorLink
# COMPOSANTE : Serveur de Messagerie en Temps Réel (Flask-SocketIO)
# AUTEUR : hermas22
# ==============================================================================

# Ici je vais importer des modules pour le serveur web et gérer les connexions simultanées
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

# Initialisation de notre application Flask
app = Flask(__name__)

# Configuration de la clé secrète pour sécuriser les sessions et les jetons de l'application
app.config['SECRET_KEY'] = 'secret_key_ifri_mentorlink'

# Initialisation du moteur SocketIO avec autorisation CORS globale (*) pour éviter les blocages de requêtes
socketio = SocketIO(app, cors_allowed_origins="*")
# GESTION DES ÉVÉNEMENTS DU CHAT

# Événement 'join' : Déclenché lorsqu'un étudiant ouvre une discussion.
# Permet de regrouper l'expéditeur et le destinataire dans un canal isolé (Room)
# pour que leurs messages restent privés.
@socketio.on('join')
def on_join(data):
    # Extraction et conversion en chaîne de l'ID unique de la conversation
    room = str(data.get('id_Convers'))
    
    # Connexion technique de l'utilisateur à ce salon spécifique
    join_room(room)

# Événement 'send_message' : Déclenché dès qu'un utilisateur clique sur "Envoyer".
# Réceptionne les données du message et les redistribue instantanément aux membres de la room.
@socketio.on('send_message')
def handle_message(data):
    # Identification du salon de discussion cible
    room = str(data.get('id_Convers'))
    
    # Structuration du dictionnaire (payload) contenant les informations du message reçu
    payload = {
        'id_Convers': data.get('id_Convers'),  # ID de la discussion concernée
        'id_Expedit': data.get('id_Expedit'),  # ID de l'étudiant qui envoie le message
        'contenu': data.get('contenu')         # Corps du message textuel
    }
    
    # Diffusion instantanée (emit) du payload à tous les utilisateurs connectés dans cette room
    emit('receive_message', payload, room=room)
 #POINT D'ENTRÉE DU SCRIPT

# Lancement du serveur de chat dédié sur le port 5001 avec le mode debug activé pour les tests
if __name__ == '__main__':
    socketio.run(app, debug=True, port=5001)