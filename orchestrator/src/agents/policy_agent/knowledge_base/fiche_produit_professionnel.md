# Fiche Produit — Crédit Professionnel

**Établissement :** Amen Bank S.A. (exemple fictif)  
**Produit :** Crédit aux Professionnels, PME et Indépendants  
**Code produit :** PRO-SME-2024  
**Version :** Janvier 2024

---

## Section 1 — Présentation du produit

### 1.1 Définition et périmètre

Le crédit professionnel est un financement destiné aux entrepreneurs individuels, artisans, professions libérales, commerçants et PME souhaitant financer leurs besoins d'exploitation ou d'investissement. Il est traité par la direction des crédits professionnels avec des règles d'éligibilité différentes du crédit retail.

### 1.2 Catégories de bénéficiaires

- **Professions libérales** : médecins, avocats, ingénieurs, architectes, experts-comptables
- **Artisans et commerçants** : avec patente ou carte professionnelle valide
- **Entrepreneurs individuels** : enregistrés au registre du commerce
- **TPE/PME** : chiffre d'affaires annuel entre 100 000 TND et 30 000 000 TND
- **Auto-entrepreneurs** : régime fiscal forfaitaire, activité depuis ≥ 2 ans

---

## Section 2 — Types de crédits professionnels

### 2.1 Crédit d'investissement

Financement de l'acquisition de biens durables à usage professionnel :
- Matériel et équipements professionnels
- Véhicules utilitaires et engins
- Aménagement et rénovation de locaux professionnels
- Acquisition de fonds de commerce
- Acquisition de locaux professionnels (bureau, atelier, commerce)

**Durée :** 3 à 15 ans  
**Montant :** 10 000 à 5 000 000 TND

**Identifiant de règle :** `PRO-INV-001`

### 2.2 Crédit d'exploitation (court terme)

Financement du cycle d'exploitation :
- Facilité de caisse (découvert autorisé)
- Escompte commercial
- Avance sur créances professionnelles
- Ligne de crédit revolving pour stocks

**Durée :** 3 à 24 mois  
**Montant :** 5 000 à 1 000 000 TND  
**Renouvellement :** annuel, sous révision de la situation financière

**Identifiant de règle :** `PRO-EXP-001`

### 2.3 Crédit de démarrage (Start-up professionnelle)

Pour les activités de moins de 3 ans :
- Montant maximum : 100 000 TND (en ligne avec dispositif BFPME)
- Garantie SOTUGAR obligatoire ou garantie personnelle renforcée
- Accompagnement par un organisme d'appui à l'entrepreneuriat (CEPEX, APII)

**Identifiant de règle :** `PRO-START-001`

---

## Section 3 — Conditions d'éligibilité

### 3.1 Conditions générales

| Critère | Condition minimale |
|---------|-------------------|
| Âge dirigeant | 21 ans minimum, 65 ans maximum |
| Ancienneté d'activité | ≥ 3 ans (2 ans pour certains secteurs prioritaires) |
| Situation fiscale | Régularisée (attestation fiscale en règle) |
| Situation CNSS | Régularisée (attestation CNSS à jour) |
| Historique bancaire | Aucun chèque sans provision > 6 mois |
| Classification CR-BCT | Classe 0 ou 1 (APPROVE ou REFER), Classe 2 (REFER uniquement) |

**Identifiant de règle :** `PRO-ELIG-001`

### 3.2 Conditions financières minimales

| Type de crédit | Chiffre d'affaires annuel minimum | Revenu net minimum |
|----------------|-----------------------------------|--------------------|
| Crédit d'exploitation ≤ 50 000 TND | 100 000 TND CA | Bénéfice net > 0 (2 derniers exercices) |
| Crédit d'exploitation > 50 000 TND | 200 000 TND CA | Bénéfice net positif sur 2 ans + plan prévisionnel |
| Crédit d'investissement ≤ 200 000 TND | 150 000 TND CA | Taux rentabilité ≥ 8 % |
| Crédit d'investissement > 200 000 TND | 500 000 TND CA | Audit financier externe requis |

**Identifiant de règle :** `PRO-FIN-001`

### 3.3 Taux d'endettement professionnel

Le taux d'endettement pour les professionnels est calculé sur la base du **résultat net fiscal** (et non le chiffre d'affaires) :

```
Taux endettement professionnel = (Annuités totales / Résultat net fiscal) × 100
```

Plafond : **33 % pour les indépendants** et **40 % pour les entreprises avec bilans certifiés** — règle BCT-2024-DTI-001.

---

## Section 4 — Caractéristiques financières

### 4.1 Montants et durées

| Type | Montant min | Montant max | Durée max |
|------|-------------|-------------|-----------|
| Exploitation CT | 5 000 TND | 1 000 000 TND | 24 mois |
| Investissement MT | 10 000 TND | 2 000 000 TND | 7 ans |
| Investissement LT (immobilier pro) | 50 000 TND | 5 000 000 TND | 15 ans |

**Identifiant de règle :** `PRO-PARAM-001`

### 4.2 Taux d'intérêt

| Type de crédit | TAEG |
|----------------|------|
| Exploitation CT | TMM + 4,0 % à 4,5 % ≈ **11,97 % à 12,47 %** |
| Investissement MT | TMM + 3,5 % à 4,0 % ≈ **11,47 % à 11,97 %** |
| Investissement LT (immobilier) | TMM + 3,0 % à 3,5 % ≈ **10,97 % à 11,47 %** |
| TEGM maximal (professionnel) | **12,47 %** — règle BCT-2024-RATE-001 |

---

## Section 5 — Garanties requises

### 5.1 Garanties selon le type de crédit

| Type de crédit | Garantie principale | Garantie complémentaire |
|----------------|---------------------|-------------------------|
| Exploitation < 50 000 TND | Caution personnelle dirigeant | Nantissement du fonds de commerce |
| Exploitation ≥ 50 000 TND | Nantissement fonds de commerce + hypothèque | Caution solidaire associé principal |
| Investissement (équipement) | Nantissement du matériel financé | Caution personnelle dirigeant |
| Investissement (immobilier) | Hypothèque premier rang | Assurance multirisque professionnelle |
| Start-up < 100 000 TND | Garantie SOTUGAR (50 %) | Caution personnelle |

**Identifiant de règle :** `PRO-GAR-001`

### 5.2 Garantie SOTUGAR

La SOTUGAR (Société Tunisienne de Garantie) peut couvrir jusqu'à **70 %** du montant du crédit pour les entreprises éligibles (PME de moins de 5 ans, secteurs prioritaires). Les frais de garantie SOTUGAR sont à la charge de l'emprunteur (1,5 % à 2,5 % du montant garanti par an).

---

## Section 6 — Documents requis

### 6.1 Documents juridiques

- Statuts de la société (pour les personnes morales)
- Extrait du registre du commerce de moins de 3 mois
- Patente ou carte professionnelle valide
- CIN du dirigeant/gérant/associé principal

### 6.2 Documents financiers

- Bilans et comptes de résultat des 3 derniers exercices (certifiés par expert-comptable agréé)
- Déclarations fiscales (IS ou IRPP) des 3 dernières années
- Attestation de situation fiscale en règle (de moins de 3 mois)
- Attestation de situation CNSS en règle
- Relevés de compte professionnel des 6 derniers mois

### 6.3 Documents du projet (crédit investissement)

- Plan de financement détaillé
- Devis ou factures proforma des équipements ou travaux
- Business plan ou plan prévisionnel sur 3 ans
- Autorisations d'exploitation (si applicable : licence, agrément ministériel)

---

## Section 7 — Règles de décision spécifiques au crédit professionnel

### 7.1 Critères d'approbation automatique (APPROVE)

- Ancienneté ≥ 5 ans ET bénéfice net positif 3 derniers exercices ET classification CR-BCT Classe 0/1
- Taux d'endettement professionnel ≤ 25 % ET montant ≤ 100 000 TND

**Identifiant de règle :** `PRO-DEC-APPROVE-001`

### 7.2 Critères de renvoi au comité (REFER)

- Activité entre 2 et 5 ans
- Perte sur l'un des 2 derniers exercices mais tendance favorable
- Montant > 500 000 TND (toujours soumis au comité de crédit)
- Classification CR-BCT Classe 2
- Secteur d'activité à risque élevé (construction, restauration, commerce de détail)

**Identifiant de règle :** `PRO-DEC-REFER-001`

### 7.3 Critères de rejet automatique (REJECT)

- Ancienneté d'activité < 2 ans sans accompagnement BFPME/APII
- Bénéfice net négatif sur les 2 derniers exercices
- Taux d'endettement professionnel > 40 %
- Classification CR-BCT ≥ Classe 3
- Situation fiscale ou CNSS non régularisée
- Chèque sans provision non régularisé sur les 12 derniers mois

**Identifiant de règle :** `PRO-DEC-REJECT-001`

---

## Section 8 — Secteurs prioritaires et dispositifs spéciaux

### 8.1 Secteurs bénéficiant de conditions préférentielles

Conformément aux orientations du Ministère des Finances et de la BCT, les secteurs suivants bénéficient de conditions de financement améliorées (taux bonifié de 1 % à 1,5 %) :

- Agriculture et pêche
- Industries manufacturières exportatrices
- Technologies de l'information et de la communication (TIC)
- Énergies renouvelables
- Santé et éducation privée
- Tourisme (sous conditions de classement)

**Identifiant de règle :** `PRO-SECT-001`

### 8.2 Lignes de refinancement BCT

Dans le cadre des mécanismes de refinancement de la BCT, certains crédits professionnels peuvent bénéficier de lignes de refinancement dédiées permettant de réduire le coût de financement de **0,5 % à 2 %** selon le dispositif applicable.
