from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(_name_)
app.config['SECRET_KEY'] = 'secret_key_ifri_mentorlink'
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('join')
def on_join(data):
    room = str(data.get('id_Convers'))
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    room = str(data.get('id_Convers'))
    
    payload = {
        'id_Convers': data.get('id_Convers'),
        'id_Expedit': data.get('id_Expedit'),
        'contenu': data.get('contenu')
    }
    
    emit('receive_message', payload, room=room)

if _name_ == '_main_':
    socketio.run(app, debug=True, port=5001)