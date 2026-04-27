# Centrale des Risques — Banque Centrale de Tunisie

**Source :** Note explicative BCT — Direction de la Supervision Bancaire  
**Référence :** Note n°2023-DSB-07  
**Objet :** Fonctionnement et utilisation de la Centrale des Risques dans le processus d'octroi de crédit

---

## Section 1 — Présentation de la Centrale des Risques BCT

### 1.1 Définition et périmètre

La Centrale des Risques de la Banque Centrale de Tunisie (CR-BCT) est un système centralisé de collecte et de partage d'informations sur les engagements de crédit. Toutes les banques agréées opérant en Tunisie sont tenues de déclarer mensuellement leurs encours de crédit à la BCT.

Le périmètre de déclaration couvre :
- Tous les crédits accordés aux personnes physiques (particuliers et professionnels)
- Tous les crédits accordés aux personnes morales (entreprises)
- Les engagements hors-bilan (cautions, garanties, lignes de crédit non tirées)
- Les crédits en défaut et créances douteuses

### 1.2 Seuil de déclaration

Tout crédit d'un montant **supérieur ou égal à 1 000 TND** doit être déclaré à la Centrale des Risques.

**Identifiant de règle :** `CR-BCT-SEUIL-001`

---

## Section 2 — Classification des risques clients

### 2.1 Grille de classification standardisée

La BCT utilise une classification en 6 classes (0 à 5) pour catégoriser la qualité des engagements :

**Classe 0 — Aucun engagement**
- L'emprunteur n'a aucun crédit déclaré à la Centrale des Risques.
- Profil : primo-emprunteur ou client sans antécédent bancaire.
- Impact sur la décision : Neutre. Aucun frein réglementaire. La décision repose sur les critères internes de la banque.

**Classe 1 — Engagement courant**
- Crédits en cours de remboursement sans incident de paiement.
- Retards éventuels : inférieurs à 30 jours, caractère ponctuel.
- Impact : Éligible sans restriction réglementaire.

**Classe 2 — Engagement nécessitant une surveillance**
- Retards de paiement entre 30 et 90 jours, ou encours cumulés représentant un risque potentiel.
- Facteurs aggravants : dégradation récente de la situation financière, secteur d'activité en difficulté.
- Impact : Dossier à soumettre au comité de crédit (REFER). Décision automatique interdite.

**Identifiant de règle :** `CR-BCT-CLASS-002`

**Classe 3 — Engagement incertain**
- Retards de paiement entre 90 et 180 jours.
- Le remboursement intégral est incertain sans recours aux garanties.
- Impact : **REJECT automatique**. Aucune dérogation possible sans régularisation préalable.

**Identifiant de règle :** `CR-BCT-CLASS-003`

**Classe 4 — Engagement préoccupant**
- Retards supérieurs à 180 jours.
- Provisionnement partiel ou total par la banque déclarante.
- Impact : **REJECT automatique**. Le client doit régulariser l'ensemble de ses impayés avant toute nouvelle demande.

**Identifiant de règle :** `CR-BCT-CLASS-004`

**Classe 5 — Créance irrécouvrable / Perte**
- Crédit passé en perte totale. Procédure judiciaire en cours ou clôturée.
- Impact : **REJECT automatique + inscription liste noire BCT** pour une durée de 5 ans.

**Identifiant de règle :** `CR-BCT-CLASS-005`

---

## Section 3 — Processus de consultation obligatoire

### 3.1 Moment de la consultation

La consultation de la Centrale des Risques est obligatoire à deux moments :

1. **Avant toute décision d'octroi** : la banque doit consulter la CR-BCT et en intégrer le résultat dans le dossier de crédit.
2. **Au moment du déblocage des fonds** : une seconde consultation est recommandée si plus de 30 jours se sont écoulés depuis la première.

**Identifiant de règle :** `CR-BCT-PROC-001`

### 3.2 Données retournées par la Centrale des Risques

La consultation retourne les informations suivantes :
- Classe de risque actuelle (0 à 5)
- Encours total de crédits déclarés (en TND)
- Nombre d'établissements créanciers
- Historique des incidents (retards, impayés) sur 36 mois glissants
- Présence ou absence dans la liste des interdits bancaires

### 3.3 Cas de non-consultation

Accorder un crédit sans consultation préalable de la CR-BCT expose l'établissement à :
- Amende administrative de 50 000 TND à 500 000 TND
- Rapport d'inspection défavorable
- Obligation de constituer des provisions supplémentaires

---

## Section 4 — Règles de cumul d'endettement

### 4.1 Encours maximal autorisé par profil

| Catégorie d'emprunteur | Encours total CR-BCT maximal |
|------------------------|------------------------------|
| Revenu mensuel < 1 500 TND | 3× revenu annuel net |
| Revenu mensuel 1 500 – 5 000 TND | 5× revenu annuel net |
| Revenu mensuel > 5 000 TND | 7× revenu annuel net |
| Retraité | 3× pension annuelle nette |

**Identifiant de règle :** `CR-BCT-CUMUL-001`

### 4.2 Calcul de l'encours incluant le nouveau crédit

L'encours total utilisé pour le calcul inclut :
- Tous les crédits existants déclarés à la CR-BCT (encours restant dû)
- Le montant du nouveau crédit demandé
- Les engagements hors-bilan si le client est caution solidaire d'un tiers

### 4.3 Règle de dépassement d'encours

Si l'encours total (existant + nouveau crédit) dépasse le plafond réglementaire :
- **REJECT automatique** si dépassement > 10 % du plafond
- **REFER au comité** si dépassement ≤ 10 % du plafond, avec justification obligatoire

**Identifiant de règle :** `CR-BCT-CUMUL-002`

---

## Section 5 — Vérification des listes de sanctions

### 5.1 Obligation de contrôle

Avant tout déblocage de fonds, l'établissement doit vérifier que l'emprunteur ne figure pas sur :
- La liste des personnes sanctionnées par le Comité Tunisien des Sanctions Financières (CTSF)
- Les listes OFAC (Office of Foreign Assets Control — US)
- Les listes de l'Union Européenne (règlements UE en vigueur)
- Les listes GAFI (Groupe d'Action Financière)

**Identifiant de règle :** `CR-BCT-SANC-001`

### 5.2 Résultats de la vérification

| Résultat | Action requise |
|----------|----------------|
| Aucune correspondance | Procédure normale |
| Correspondance partielle (similitude > 80 %) | REFER — vérification manuelle obligatoire |
| Correspondance confirmée | REJECT immédiat + signalement CTAF (Cellule de Traitement des Renseignements Financiers) |

**Identifiant de règle :** `CR-BCT-SANC-002`

---

## Section 6 — Déclaration des incidents de paiement

### 6.1 Délai de déclaration

Tout retard de paiement supérieur à **30 jours** doit être déclaré à la Centrale des Risques dans les **15 jours ouvrables** suivant le constat.

### 6.2 Mise à jour des informations

Les informations déclarées doivent être mises à jour mensuellement. En cas de régularisation (remboursement des impayés), la banque est tenue de mettre à jour le statut du client dans les **10 jours ouvrables**.

### 6.3 Droit de rectification

Tout client peut, sur demande écrite, obtenir communication des informations le concernant à la Centrale des Risques et demander la rectification d'informations erronées.
