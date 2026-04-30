# Fiche Produit — Crédit Auto

**Établissement :** Amen Bank S.A. (exemple fictif)  
**Produit :** Crédit Automobile — Véhicule Neuf et d'Occasion  
**Code produit :** AUTO-VEH-2024  
**Version :** Janvier 2024

---

## Section 1 — Présentation du produit

### 1.1 Définition

Le crédit auto est un prêt affecté destiné exclusivement à l'acquisition d'un véhicule à moteur à usage personnel ou professionnel. Il est garanti par le nantissement du véhicule financé (gage automobile inscrit au registre des nantissements).

### 1.2 Types de véhicules financés

- Véhicules de tourisme neufs (de marque quelconque, importés ou assemblés en Tunisie)
- Véhicules de tourisme d'occasion de moins de 7 ans
- Véhicules utilitaires légers (PTAC ≤ 3,5 tonnes) — usage professionnel justifié
- Motocycles et scooters neufs jusqu'à 30 000 TND

**Sont exclus :** Véhicules > 7 ans, véhicules accidentés, véhicules de compétition, engins agricoles.

---

## Section 2 — Conditions d'éligibilité

### 2.1 Profil emprunteur

| Critère | Condition minimale |
|---------|-------------------|
| Âge minimum | 21 ans (permis de conduire valide exigé) |
| Âge maximum | 65 ans à la date de demande — règle BCT-2024-AGE-003 |
| Âge à l'échéance | Maximum 72 ans |
| Statut professionnel | Salarié, retraité, indépendant > 2 ans |
| Revenu mensuel net minimum | **1 000 TND/mois** |
| Taux d'endettement post-crédit | ≤ 40 % — règle BCT-2024-DTI-001 |

**Identifiant de règle :** `AUTO-ELIG-001`

### 2.2 Conditions liées au véhicule

| Type de véhicule | Condition d'éligibilité |
|-----------------|-------------------------|
| Neuf | Facture constructeur ou concessionnaire agréé |
| Occasion < 3 ans | Expertise obligatoire + carte grise originale |
| Occasion 3–7 ans | Expertise obligatoire + contrôle technique valide |
| Occasion > 7 ans | **Non finançable** — règle BCT-2024-LTV-002 |

---

## Section 3 — Caractéristiques financières

### 3.1 Montants

| Paramètre | Valeur |
|-----------|--------|
| Montant minimum | **5 000 TND** |
| Montant maximum — véhicule neuf | **150 000 TND** |
| Montant maximum — véhicule occasion | **80 000 TND** |
| Financement maximal — neuf (LTV) | **85 % de la valeur facture TTC** — règle BCT-2024-LTV-002 |
| Financement maximal — occasion < 3 ans | **75 % de la valeur expertise** |
| Financement maximal — occasion 3–7 ans | **65 % de la valeur expertise** |
| Apport personnel minimum | **15 % à 35 % selon l'ancienneté du véhicule** |

**Identifiant de règle :** `AUTO-MONTANT-001`

### 3.2 Durée

| Paramètre | Valeur |
|-----------|--------|
| Durée minimale | 12 mois |
| Durée maximale — véhicule neuf | **84 mois (7 ans)** — règle BCT-2024-DUR-001 |
| Durée maximale — occasion < 3 ans | **72 mois (6 ans)** |
| Durée maximale — occasion 3–7 ans | **48 mois (4 ans)** |

**Règle de durée liée à l'âge du véhicule :** La durée du crédit + l'âge du véhicule à la date de la demande ne peut dépasser **10 ans**. Pour un véhicule de 4 ans, la durée maximale est donc 6 ans.

**Identifiant de règle :** `AUTO-DUR-001`

### 3.3 Taux d'intérêt

| Profil | TAEG |
|--------|------|
| Risque faible (PD < 0,25) — neuf | TMM + 3,5 % ≈ **11,47 %** |
| Risque standard (PD 0,25–0,40) — neuf | TMM + 4,0 % ≈ **11,97 %** |
| Risque élevé (PD 0,40–0,65) — neuf | TMM + 4,0 % ≈ **11,97 %** (TEGM max) |
| Véhicule occasion (toutes classes) | TMM + 4,0 % ≈ **11,97 %** |
| TEGM légal maximal — crédit auto | **11,97 %** — règle BCT-2024-RATE-001 |

---

## Section 4 — Garanties et assurances

### 4.1 Garantie principale

**Gage automobile (nantissement)** inscrit au registre des nantissements de la recette des finances compétente. La carte grise reste en possession de la banque jusqu'au remboursement intégral.

**Identifiant de règle :** `AUTO-GAR-001`

### 4.2 Assurances obligatoires

| Assurance | Obligation |
|-----------|-----------|
| Assurance tous risques (véhicule) | **Obligatoire** pour la durée du crédit |
| Assurance ADIP (décès-invalidité) | Obligatoire si crédit > 50 000 TND |
| Assurance perte d'emploi | Facultative, fortement recommandée |

L'attestation d'assurance tous risques doit mentionner la banque comme bénéficiaire en cas de sinistre total.

**Identifiant de règle :** `AUTO-ASS-001`

---

## Section 5 — Documents requis

### 5.1 Documents emprunteur

- CIN valide (recto-verso)
- Permis de conduire valide (copie)
- 3 derniers bulletins de paie ou justificatifs de revenus
- Relevés de compte des 3 derniers mois

### 5.2 Documents véhicule

**Véhicule neuf :**
- Facture proforma du concessionnaire
- Bon de commande signé

**Véhicule d'occasion :**
- Carte grise originale
- Rapport d'expertise établi par un expert agréé BCT
- Contrôle technique de moins de 6 mois
- Certificat de non-gage de moins de 3 mois

---

## Section 6 — Règles de décision spécifiques au crédit auto

### 6.1 Critères d'approbation automatique (APPROVE)

- PD < 0,35 ET taux d'endettement ≤ 33 % ET aucun incident CR-BCT ET véhicule neuf ou occasion < 3 ans
- Revenu ≥ 2 000 TND ET montant ≤ 50 000 TND ET ancienneté emploi ≥ 12 mois

**Identifiant de règle :** `AUTO-DEC-APPROVE-001`

### 6.2 Critères de renvoi au comité (REFER)

- PD entre 0,35 et 0,65
- Véhicule d'occasion entre 3 et 7 ans avec PD entre 0,25 et 0,35
- Taux d'endettement entre 36 % et 40 %
- Montant > 100 000 TND (véhicule de luxe)

**Identifiant de règle :** `AUTO-DEC-REFER-001`

### 6.3 Critères de rejet automatique (REJECT)

- Taux d'endettement > 40 %
- PD ≥ 0,65
- Véhicule > 7 ans
- Âge emprunteur > 65 ans
- Âge emprunteur à l'échéance > 72 ans
- Classification CR-BCT ≥ Classe 3
- LTV demandé > 85 % (neuf) ou > 75 % (occasion < 3 ans) ou > 65 % (occasion 3–7 ans)

**Identifiant de règle :** `AUTO-DEC-REJECT-001`

---

## Section 7 — Cas particuliers

### 7.1 Crédit auto pour taxi et transport en commun

Les véhicules à usage commercial (taxi, louage) bénéficient d'un régime dérogatoire :
- LTV maximal : **90 %** avec agrément préfectoral en cours de validité
- Durée maximale : 7 ans
- Justificatif d'activité : carte de taxi ou agrément de transport en cours de validité

### 7.2 Crédit auto — Tunisien Résidant à l'Étranger (TRE)

- Revenu justifié par attestation consulaire ou fiches de paie étrangères
- Garant tunisien résidant en Tunisie obligatoire
- Apport minimum : 30 % de la valeur du véhicule
- Durée maximale : 60 mois
