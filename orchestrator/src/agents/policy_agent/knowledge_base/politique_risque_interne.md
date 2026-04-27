# Politique de Risque de Crédit Interne — Amen Bank (fictif)

**Établissement :** Amen Bank S.A. (exemple fictif — à des fins de simulation RAG)  
**Document :** Politique de Risque Crédit Retail — Version 3.2  
**Date de mise à jour :** Janvier 2024  
**Validé par :** Comité des Risques et de la Conformité

---

## Section 1 — Objectifs et périmètre

### 1.1 Objectif

La présente politique définit les règles internes d'octroi, de gestion et de surveillance des crédits accordés aux particuliers et aux professionnels. Elle est conçue pour respecter les exigences de la Banque Centrale de Tunisie (BCT) tout en maintenant un portefeuille de crédit sain et rentable.

### 1.2 Périmètre d'application

Cette politique s'applique à :
- Tous les crédits aux particuliers (immobilier, auto, consommation)
- Tous les crédits aux professionnels indépendants
- Les crédits accordés via les canaux digitaux (banque en ligne, application mobile)
- Les décisions prises par le système de scoring automatique

---

## Section 2 — Bandes de risque et seuils de décision

### 2.1 Définition des bandes de risque

Le système de scoring interne calcule une **probabilité de défaut (PD)** pour chaque demande. La PD est exprimée entre 0 et 1.

| Bande de risque | Seuil PD | Décision automatique |
|-----------------|----------|----------------------|
| **AAA — Très faible risque** | PD < 0,20 | APPROVE automatique |
| **AA — Faible risque** | 0,20 ≤ PD < 0,35 | APPROVE automatique |
| **A — Risque modéré** | 0,35 ≤ PD < 0,50 | **REFER — zone grise basse** |
| **BBB — Risque élevé** | 0,50 ≤ PD < 0,65 | **REFER — zone grise haute** |
| **BB — Risque très élevé** | 0,65 ≤ PD < 0,80 | REJECT automatique |
| **B — Risque critique** | PD ≥ 0,80 | REJECT automatique + note comité |

**Identifiant de règle :** `RISK-INT-BAND-001`

### 2.2 Zone grise — Règle du human-in-the-loop

Tout dossier dont la PD est comprise entre **0,35 et 0,65** (zone grise) doit obligatoirement être :
1. Transmis à un conseiller crédit pour examen approfondi
2. Accompagné d'un rapport XAI complet (SHAP values, facteurs principaux, contrefactuels)
3. Soumis au comité de crédit si le montant dépasse 100 000 TND

**Il est formellement interdit de contourner le comité de crédit pour les dossiers en zone grise.**

**Identifiant de règle :** `RISK-INT-GREY-001`

### 2.3 Confiance du modèle

Si la confiance du modèle de scoring est inférieure à **0,70** (indépendamment de la PD), le dossier doit être traité comme zone grise et référé au conseiller.

**Identifiant de règle :** `RISK-INT-CONF-001`

---

## Section 3 — Critères de rejet immédiat (Hard Stops)

### 3.1 Liste des critères de rejet automatique inconditionnel

Les conditions suivantes entraînent un rejet immédiat (REJECT) sans possibilité de dérogation :

| ID Règle | Critère | Valeur seuil |
|----------|---------|--------------|
| `RISK-INT-STOP-001` | Taux d'endettement post-crédit | > 40 % |
| `RISK-INT-STOP-002` | Classification Centrale des Risques | Classe 3, 4 ou 5 |
| `RISK-INT-STOP-003` | Présence sur liste de sanctions | Correspondance confirmée |
| `RISK-INT-STOP-004` | Âge emprunteur | < 18 ans |
| `RISK-INT-STOP-005` | Âge à l'échéance du crédit | > 70 ans |
| `RISK-INT-STOP-006` | Résidence hors Tunisie (sans garant résident) | Oui |
| `RISK-INT-STOP-007` | Impayés non régularisés auprès de la banque | Oui |
| `RISK-INT-STOP-008` | Fraude documentaire détectée | Oui |
| `RISK-INT-STOP-009` | Score fraude agent > 0,80 | Oui |

### 3.2 Rejet pour raison réglementaire BCT

Tout rejet fondé sur une règle BCT doit mentionner explicitement le numéro de la circulaire et l'article applicable dans le motif de refus transmis au client (conformité GDPR Art. 22).

---

## Section 4 — Règles d'éligibilité par profil emprunteur

### 4.1 Salariés du secteur public

- Ancienneté minimale : **6 mois** dans le poste actuel
- Contrat : CDI uniquement ou fonctionnaire titulaire
- Revenu minimum : **800 TND/mois** net (crédit consommation), **1 500 TND/mois** (crédit immobilier)
- Domiciliation de salaire fortement recommandée (réduction de taux possible)

**Identifiant de règle :** `RISK-INT-PROF-001`

### 4.2 Salariés du secteur privé

- Ancienneté minimale : **1 an** dans l'entreprise actuelle
- Contrat : CDI de préférence. CDD accepté si durée restante ≥ 24 mois
- Revenu minimum : **1 000 TND/mois** net (crédit consommation), **2 000 TND/mois** (crédit immobilier)
- Attestation de salaire et 3 derniers bulletins de paie obligatoires

**Identifiant de règle :** `RISK-INT-PROF-002`

### 4.3 Travailleurs indépendants et professions libérales

- Ancienneté d'activité minimale : **3 ans** (carte professionnelle ou patente)
- Chiffre d'affaires déclaré fiscalement depuis au moins 2 exercices
- Revenu retenu : moyenne des 2 derniers exercices fiscaux confirmés
- Apport personnel minimal : **20 %** du montant financé

**Identifiant de règle :** `RISK-INT-PROF-003`

### 4.4 Retraités

- Pension mensuelle nette minimale : **700 TND** (crédit consommation), **1 200 TND** (crédit auto)
- Âge maximum à la demande : **68 ans**
- Assurance ADIP obligatoire, quelle que soit la durée
- Durée maximale : 10 ans pour consommation, 5 ans pour auto

**Identifiant de règle :** `RISK-INT-PROF-004`

---

## Section 5 — Règles de cumul et concentration des risques

### 5.1 Encours maximal par client

Un même client ne peut avoir plus de **3 crédits actifs simultanément** auprès de la banque (hors crédit immobilier principal).

**Identifiant de règle :** `RISK-INT-CUM-001`

### 5.2 Règle de ratio prêt/revenu annuel

Le montant total du crédit accordé (tous types confondus) ne peut excéder **8 fois le revenu annuel net** du client. Pour les crédits immobiliers seuls, le plafond est de **5 fois le revenu annuel net**.

**Identifiant de règle :** `RISK-INT-CUM-002`

---

## Section 6 — Politique de tarification et conditions

### 6.1 Barème de taux selon le risque

| Bande de risque | Taux de base (hors assurance) |
|-----------------|-------------------------------|
| AAA — AA | TMM + 2,0 % à 2,5 % |
| A | TMM + 3,0 % à 3,5 % |
| BBB | TMM + 4,0 % à 4,5 % |

Aucun taux accordé ne peut dépasser le TEGM fixé par la BCT.

### 6.2 Frais de dossier

| Montant crédit | Frais de dossier |
|----------------|------------------|
| < 20 000 TND | 200 TND (fixe) |
| 20 000 – 100 000 TND | 0,5 % du montant |
| > 100 000 TND | 0,3 % du montant (plafonnés à 2 000 TND) |

---

## Section 7 — Audit et conformité

### 7.1 Journal d'audit immuable

Toute décision (APPROVE, REFER, REJECT) doit être enregistrée dans le journal d'audit avec :
- Identifiant unique de la décision
- Timestamp UTC
- PD score et version du modèle utilisé
- Identifiants de toutes les règles évaluées
- Identifiant de la règle déclenchante (rule_id)
- Identifiant de l'agent ou du conseiller ayant pris la décision

**Le journal d'audit est en mode append-only. Aucune modification ou suppression d'entrée n'est autorisée.**

**Identifiant de règle :** `RISK-INT-AUDIT-001`

### 7.2 Conservation des données

Les données de décision de crédit et les logs d'audit doivent être conservés pendant **10 ans** conformément à la réglementation bancaire tunisienne et aux recommandations Bâle III.
