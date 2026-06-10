/* Projet : IFRI_MentorLink
   Groupe : 65
   Fichier : database.sql
   Role : Creation et initialisation de la base de donnees du projet
   Auteur : LenoumiBel-Mira & Sergius
   Date : 05/06/2026
*/

-- Creation de la Base de Donnees proprement dite
CREATE DATABASE IF NOT EXISTS mentorlink;
USE mentorlink;

-- 1. Table FILIERE
CREATE TABLE filiere (
    id_Fil INT AUTO_INCREMENT PRIMARY KEY,
    lib_Fil VARCHAR(50) NOT NULL UNIQUE
);

-- 2. Table NIVEAU
CREATE TABLE niveau (
    id_Niv INT AUTO_INCREMENT PRIMARY KEY,
    lib_Niv VARCHAR(50) NOT NULL UNIQUE
);

-- 3. Table MATIERE
CREATE TABLE matiere (
    id_Mat INT AUTO_INCREMENT PRIMARY KEY,
    lib_Mat VARCHAR(100) NOT NULL UNIQUE
);

-- 4. Table COURS : represente le couple (filiere, niveau)
--    Ex: cours #1 = "GL en Licence 1"
CREATE TABLE cours (
    id_Cours INT AUTO_INCREMENT PRIMARY KEY,
    lib_Cours VARCHAR(50) NOT NULL,
    id_Fil INT NOT NULL,
    id_Niv INT NOT NULL,
    FOREIGN KEY (id_Fil) REFERENCES filiere(id_Fil) ON DELETE CASCADE,
    FOREIGN KEY (id_Niv) REFERENCES niveau(id_Niv) ON DELETE CASCADE,
    UNIQUE KEY uniq_fil_niv (id_Fil, id_Niv)
);

-- 5. Table COURS_MATIERE : ASSOCIATION DEFINIR qui lie cours <-> matiere
--    C'est ce qui definit quelles matieres sont enseignees
--    pour une filiere donnee a un niveau donne.
CREATE TABLE cours_matiere (
    id_Cours INT NOT NULL,
    id_Mat INT NOT NULL,
    PRIMARY KEY (id_Cours, id_Mat),
    FOREIGN KEY (id_Cours) REFERENCES cours(id_Cours) ON DELETE CASCADE,
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat) ON DELETE CASCADE
);

-- 6. TABLE UTILISATEUR
CREATE TABLE utilisateur (
    id_User INT AUTO_INCREMENT PRIMARY KEY,
    nom VARCHAR(100) NOT NULL,
    prenom VARCHAR(100) NOT NULL,
    tel INT UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    mdp VARCHAR(255) NOT NULL,
    photo VARCHAR(255),
    bio TEXT,
    id_Fil INT NOT NULL,
    id_Niv INT NOT NULL,
    FOREIGN KEY (id_Fil) REFERENCES filiere(id_Fil),
    FOREIGN KEY (id_Niv) REFERENCES niveau(id_Niv)
);

-- 7. TABLE COMPETENCE
CREATE TABLE competence (
    id_User INT NOT NULL,
    id_Mat INT NOT NULL,
    maitrise BOOLEAN NOT NULL,
    PRIMARY KEY (id_User, id_Mat),
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User) ON DELETE CASCADE,
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat) ON DELETE CASCADE
);

-- 8. TABLE ANNONCE
CREATE TABLE annonce (
    id_Annonce INT AUTO_INCREMENT PRIMARY KEY,
    type_annonce VARCHAR(10) NOT NULL CHECK (type_annonce IN ('Offre','Demande')),
    format VARCHAR(20) NOT NULL CHECK (format IN ('Presentiel','En ligne','Les deux')),
    details TEXT,
    date_pub TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_User INT NOT NULL,
    id_Mat INT NOT NULL,
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User) ON DELETE CASCADE,
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat) ON DELETE CASCADE
);

-- 9. TABLE DISPONIBILITE
CREATE TABLE disponibilite (
    id_Dispo INT AUTO_INCREMENT PRIMARY KEY,
    jour VARCHAR(20) NOT NULL,
    heure_debut TIME NOT NULL,
    heure_fin TIME NOT NULL,
    id_User INT NOT NULL,
    id_Annonce INT,
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User) ON DELETE CASCADE,
    FOREIGN KEY (id_Annonce) REFERENCES annonce(id_Annonce) ON DELETE CASCADE
);

-- 10. TABLE CONVERSATION
CREATE TABLE conversation (
    id_Convers INT AUTO_INCREMENT PRIMARY KEY,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_User1 INT NOT NULL,
    id_User2 INT NOT NULL,
    FOREIGN KEY (id_User1) REFERENCES utilisateur(id_User) ON DELETE CASCADE,
    FOREIGN KEY (id_User2) REFERENCES utilisateur(id_User) ON DELETE CASCADE
);

-- 11. TABLE MESSAGE
CREATE TABLE message(
    id_Mess INT AUTO_INCREMENT PRIMARY KEY,
    contenu TEXT NOT NULL,
    date_envoie TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_Convers INT NOT NULL,
    id_Expedit INT NOT NULL,
    FOREIGN KEY (id_Convers) REFERENCES conversation(id_Convers) ON DELETE CASCADE,
    FOREIGN KEY (id_Expedit) REFERENCES utilisateur(id_User) ON DELETE CASCADE
);

-- ============================================================
-- SEEDING : Initialisation des donnees par defaut
-- ============================================================

-- Filieres IFRI
INSERT INTO filiere (lib_Fil) VALUES
('GL'), ('IA'), ('IM'), ('SI'), ('SE&IoT'), ('SIRI');

-- Niveaux d'etudes
INSERT INTO niveau (lib_Niv) VALUES
('Licence 1'), ('Licence 2'), ('Licence 3'), ('Master 1'), ('Master 2');

-- Matieres (catalogue global)
INSERT INTO matiere (lib_Mat) VALUES
('Algorithmique'),
('TEEO'),
('Anglais technique'),
('Droits et deontologie liee au TIC'),
('Projet integrateur'),
('Programmation Python'),
('Programmation C'),
('Programmation Java'),
('Base de donnees'),
('Reseaux informatiques'),
('Systemes d''exploitation'),
('Genie logiciel'),
('Intelligence artificielle'),
('Machine Learning'),
('Cybersecurite'),
('Developpement Web'),
('Developpement Mobile'),
('Mathematiques'),
('Statistiques'),
('Architecture des ordinateurs');

-- Creation des cours : 1 cours par couple (filiere, niveau) = 30 cours
-- L'admin pourra ensuite y associer/desassocier des matieres
INSERT INTO cours (lib_Cours, id_Fil, id_Niv)
SELECT CONCAT(f.lib_Fil, ' - ', n.lib_Niv), f.id_Fil, n.id_Niv
FROM filiere f CROSS JOIN niveau n;

-- Initialisation par defaut : on attache toutes les matieres a tous les cours
-- (l'admin pourra affiner ensuite)
INSERT INTO cours_matiere (id_Cours, id_Mat)
SELECT c.id_Cours, m.id_Mat
FROM cours c CROSS JOIN matiere m;

-- ============================================================
-- Index pour optimiser les performances
-- ============================================================
CREATE INDEX idx_message_conversation_date ON message(id_Convers, date_envoie ASC);
CREATE INDEX idx_conversation_participants ON conversation(id_User1, id_User2);
CREATE INDEX idx_cours_fil_niv ON cours(id_Fil, id_Niv);
CREATE INDEX idx_cours_matiere_mat ON cours_matiere(id_Mat);

-- ============================================================
-- Utilisateur MySQL dedie a l'application
-- ============================================================
DROP USER IF EXISTS 'mentorlink'@'localhost';
CREATE USER 'mentorlink'@'localhost' IDENTIFIED WITH mysql_native_password BY 'MentorLink_2026!';
GRANT ALL PRIVILEGES ON mentorlink.* TO 'mentorlink'@'localhost';
FLUSH PRIVILEGES;
