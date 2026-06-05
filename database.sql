/* Projet : IFRI_MentorLink
   Groupe : 65
   Fichier : database.sql
   Rôle : Création et initialisation de la base de données du  projet
   Auteur : LenoumiBel-Mira & Sergius
   Date : 05/06/2026
*/

--Création de la Base de Données proprement dite
CREATE DATABASE IF NOT EXISTS mentorlink;
USE mentorlink;

-- 1. Table FILIERE
CREATE TABLE filiere (
    id_Fil INT AUTO_INCREMENT PRIMARY KEY,
    lib_Fil VARCHAR (50) NOT NULL
);

-- 2. Table NIVEAU
CREATE TABLE niveau (
    id_Niv INT AUTO_INCREMENT PRIMARY KEY,
    lib_Niv VARCHAR (50) NOT NULL
);

-- 3. Table MATIERE
CREATE TABLE matiere (
    id_Mat INT AUTO_INCREMENT PRIMARY KEY,
    lib_Mat VARCHAR (50) NOT NULL
);

-- 4. Table COURS
CREATE TABLE cours (
    id_Cours INT AUTO_INCREMENT PRIMARY KEY,
    lib_Cours VARCHAR (50) NOT NULL,
    id_Fil INT NOT NULL,
    id_Niv INT NOT NULL,
    --Indications des clés étrangères
    FOREIGN KEY (id_Fil) REFERENCES filiere(id_Fil),
    FOREIGN KEY (id_Niv) REFERENCES niveau(id_Niv)
);

-- 5- Table COURS_MATIERE : ASSOCIATION DEFINIR qui lie les deux tables COURS et MATIERE
CREATE TABLE cours_matiere (
    id_Cours INT NOT NULL,
    id_Mat INT NOT NULL,
     -- Indication de la clé primaire de cette table
    PRIMARY KEY (id_Cours,id_Mat),
     --Indications des clés étrangères
    FOREIGN KEY (id_Cours) REFERENCES cours(id_Cours),
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat)
);

-- 6- TABLE UTILISATEUR
CREATE TABLE utilisateur (
    id_User INT AUTO_INCREMENT PRIMARY KEY,
    nom VARCHAR (100) NOT NULL,
    prenom VARCHAR (100) NOT NULL,
    -- UNIQUE caR le numéro de téléphone et l'email doivent être unique par utilisateur
    tel INT UNIQUE NOT NULL,
    email VARCHAR (100) UNIQUE NOT NULL,
    -- 255 pour le mdp afin de stocker le hash du mot de passe
    mdp VARCHAR (255) NOT NULL,
    -- stocke dans photo le chemin de l'image et facultative
    photo VARCHAR (255),
    -- texte libre sans limite fixe et facultative
    bio TEXT,
    id_Fil INT NOT NULL,
    id_Niv INT NOT NULL,
    FOREIGN KEY (id_Fil) REFERENCES filiere(id_Fil),
    FOREIGN KEY (id_Niv) REFERENCES niveau(id_Niv)
);

-- 7- TABLE COMPETENCE : ASSOCIATION MAITRISER qui lie les deux tables utilisateur et matiere
CREATE TABLE competence (
    id_User INT NOT NULL,
    id_Mat INT NOT NULL,
    -- Propriété portée par l'association
    maitrise BOOLEAN NOT NULL,
    PRIMARY KEY (id_User, id_Mat),
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User),
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat)
);

-- 8- TABLE ANNONCE 
CREATE TABLE annonce (
    id_Annonce INT AUTO_INCREMENT PRIMARY KEY,
    -- type est un mot cle réservé en SQL. Création d'un ensemble pour spécifier que type_annonce ne peut prendre que l'une des deux valeurs
    type_annonce VARCHAR (10) NOT NULL CHECK (type_annonce IN ('Offre','Demande')),
    -- un ensemble ici également car format ne peut prendre que l'une des trois valeurs
    format VARCHAR (20) NOT NULL CHECK (format IN ('Présentiel','En ligne','Les deux')),
    details TEXT,
    -- La date est automatiquement prise depuis l'horloge du serveur au moment de l'insertion. L'utilisateur ne remplit pas la date
    date_pub TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_User INT NOT NULL,
    id_Mat INT NOT NULL,
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User),
    FOREIGN KEY (id_Mat) REFERENCES matiere(id_Mat)
);   

-- 9- TABLE DISPONIBILITE
CREATE TABLE disponibilite (
    id_Dispo INT AUTO_INCREMENT PRIMARY KEY,
    jour VARCHAR (20) NOT NULL,
    heure_debut TIME NOT NULL,
    heure_fin TIME NOT NULL,
    id_User INT NOT NULL,
    -- Pas de NOT NULL ici car une disponibilité peut exister sans annonce : voir cardinalité (0,1) au niveau de cette table dans le MCD
    id_Annonce INT,
    FOREIGN KEY (id_User) REFERENCES utilisateur(id_User),
    FOREIGN KEY (id_Annonce) REFERENCES annonce(id_Annonce)
);

-- 10- TABLE CONVERSATION
CREATE TABLE conversation (
    id_Convers INT AUTO_INCREMENT PRIMARY KEY,
    -- Date de création enregistrée automatiquement
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    /* Une conversation implique toujours exactement 2 utilisateurs.
       id_User1 et id_User2 sont les deux participants de la conversation mais sont tous deux des utilisateurs.
       C'est la traduction de la cardinalité (2,2) definie au niveau de cette table dans le MCD:
    */
    id_User1 INT NOT NULL,
    id_User2 INT NOT NULL,
    FOREIGN KEY (id_User1) REFERENCES utilisateur(id_User),
    FOREIGN KEY (id_User2) REFERENCES utilisateur(id_User)
);

-- 11- TABLE MESSAGE
CREATE TABLE message(
    id_Mess INT AUTO_INCREMENT PRIMARY KEY,
    -- texte du message, pas de limite fixe
    contenu TEXT NOT NULL,
    -- date automatique
    date_envoie TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_Convers INT NOT NULL,
    -- l'utilisateur qui a envoyé le message
    id_Expedit INT NOT NULL,
    FOREIGN KEY (id_Convers) REFERENCES conversation(id_Convers),
    FOREIGN KEY (id_Expedit) REFERENCES utilisateur(id_User)
);

-- Initialisation dans la base précisement dans la table filière les différentes filières d'IFRI
INSERT INTO filiere (lib_Fil) 
VALUES ('GL'),
('IA'),
('IM'),
('SI'),
('SE&IoT'),
('SIRI');

-- Initiatisation dans la base précisement dans la table niveau les differents niveaux de formation à IFRI
INSERT INTO niveau (lib_Niv)
VALUES ('Licence 1'),
('Licence 2'),
('Licence 3'),
('Master 1'),
('Master 2');

-- Initialisation dans la base précisement dans la table matière quelques matières toutes filières confondues
INSERT INTO matiere (lib_Mat)
VALUES ('Algorithmique'),
('TEEO'),
('Anglais technique'),
('Droits et déontologie liée au TIC'),
('Projet integrateur');

-- Initialisation de la table cours avec quelques occurences
INSERT INTO cours (lib_Cours,id_Fil,id_Niv) VALUES
-- GL
('Semestre 1', 1, 1), -- S1 GL L1
('Semestre 2', 1, 1), -- S2 GL L1
('Semestre 1', 1, 2), -- S1 GL L2
('Semestre 2', 1, 2), -- S2 GL L2
('Semestre 1', 1, 3), -- S1 GL L3
('Semestre 2', 1, 3); -- S2 GL L3

-- Initialisation de quelques occurences de la table cours_matiere
INSERT INTO cours_matiere (id_Cours,id_Mat) VALUES
(1,1),
(1,2),
(1,3),
(1,4);