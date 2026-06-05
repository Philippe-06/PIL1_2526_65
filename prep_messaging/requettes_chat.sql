SELECT id_Expedit, contenu, date_envoie 
FROM message 
WHERE id_Convers = :id_conversation 
ORDER BY date_envoie ASC;

INSERT INTO message (contenu, id_Convers, id_Expedit) 
VALUES (:contenu, :id_conversation, :id_auteur);