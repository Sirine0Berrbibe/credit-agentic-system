# Fiche Produit — Crédit à la Consommation

**Établissement :** Amen Bank S.A. (exemple fictif)  
**Produit :** Crédit Consommation — Personnel et Affecté  
**Code produit :** CONSO-PER-2024  
**Version :** Janvier 2024

---

## Section 1 — Présentation du produit

### 1.1 Définition

Le crédit à la consommation est un prêt personnel non affecté ou affecté à un achat spécifique, accordé à des particuliers pour financer des dépenses personnelles courantes. Il ne nécessite pas de garantie réelle mais requiert une capacité de remboursement démontrée.

### 1.2 Usages éligibles

**Crédit non affecté (personnel) :**
- Dépenses personnelles (voyages, ameublement, électroménager)
- Frais médicaux et hospitaliers
- Frais de mariage ou événements familiaux
- Frais de scolarité et formation

**Crédit affecté :**
- Achat d'équipements électroniques et informatiques
- Financement de formations certifiantes
- Travaux d'aménagement intérieur < 20 000 TND

---

## Section 2 — Conditions d'éligibilité

### 2.1 Profil emprunteur

| Critère | Condition minimale |
|---------|-------------------|
| Âge minimum | 18 ans |
| Âge maximum | 65 ans à la date de demande |
| Statut professionnel | Salarié (CDI ou CDD > 12 mois restants), retraité, ou indépendant > 2 ans |
| Revenu mensuel net minimum | **800 TND/mois** |
| Taux d'endettement post-crédit | ≤ 40 % (règle BCT-2024-DTI-001) |
| Ancienneté employeur (salarié) | ≥ 6 mois |

**Identifiant de règle :** `CONSO-ELIG-001`

### 2.2 Conditions de revenu minimum par montant

| Montant demandé | Revenu mensuel net minimum requis |
|-----------------|-----------------------------------|
| ≤ 5 000 TND | 800 TND/mois |
| 5 001 – 15 000 TND | 1 200 TND/mois |
| 15 001 – 30 000 TND | 1 800 TND/mois |
| > 30 000 TND | 2 500 TND/mois + justificatif d'usage |

**Identifiant de règle :** `CONSO-REV-001`

---

## Section 3 — Caractéristiques financières

### 3.1 Montants

| Paramètre | Valeur |
|-----------|--------|
| Montant minimum | **1 000 TND** |
| Montant maximum — standard | **50 000 TND** |
| Montant maximum — client premium (revenu > 5 000 TND/mois) | **80 000 TND** |
| Montant maximum absolu | **100 000 TND** (nécessite assurance ADIP) |

**Identifiant de règle :** `CONSO-MONTANT-001`

### 3.2 Durée

| Paramètre | Valeur |
|-----------|--------|
| Durée minimale | 6 mois |
| Durée maximale standard | 84 mois (7 ans) — règle BCT-2024-DUR-001 |
| Durée maximale pour retraités | 60 mois (5 ans) |
| Durée maximale — montant < 5 000 TND | 36 mois |

### 3.3 Taux d'intérêt

| Profil de risque | Taux annuel effectif global (TAEG) |
|-----------------|-------------------------------------|
| Risque faible (PD < 0,25) | TMM + 4,5 % ≈ **12,47 %** |
| Risque standard (PD 0,25–0,40) | TMM + 5,5 % ≈ **13,47 %** |
| Risque élevé (PD 0,40–0,65) | TMM + 6,0 % ≈ **13,97 %** |
| TEGM légal maximal BCT | **14,47 %** (TMM + 6,5 %) |

**Identifiant de règle :** `CONSO-RATE-001`

### 3.4 Mensualités — exemples indicatifs

Pour un crédit de 20 000 TND sur 60 mois à 13,47 % TAEG : mensualité ≈ **455 TND/mois**  
Pour un crédit de 10 000 TND sur 36 mois à 12,47 % TAEG : mensualité ≈ **334 TND/mois**

---

## Section 4 — Garanties et assurances

### 4.1 Garanties

Le crédit consommation standard ne requiert pas de garantie réelle. Cependant :

| Situation | Garantie requise |
|-----------|-----------------|
| Montant > 30 000 TND | Caution personnelle d'un tiers ou co-emprunteur |
| Taux d'endettement entre 35 % et 40 % | Caution solidaire recommandée |
| PD entre 0,40 et 0,55 (zone grise basse) | Domiciliation de salaire obligatoire |

### 4.2 Assurance

| Montant | Assurance ADIP |
|---------|----------------|
| ≤ 50 000 TND | Recommandée (facultative) |
| > 50 000 TND | **Obligatoire** (règle BCT-2024-INS-001) |

**Identifiant de règle :** `CONSO-ASS-001`

---

## Section 5 — Documents requis

### 5.1 Pour salarié (secteur public ou privé)

- CIN valide (recto-verso)
- Derniers 3 bulletins de paie (originaux ou certifiés conformes)
- Attestation de travail de moins de 3 mois
- Relevés de compte bancaire des 3 derniers mois
- Consultation Centrale des Risques (effectuée par la banque)

### 5.2 Pour retraité

- CIN valide
- Attestation de pension (CNSS ou CNRPS) de moins de 3 mois
- Relevés de compte des 3 derniers mois

### 5.3 Pour travailleur indépendant

- CIN valide
- Patente ou carte d'identité professionnelle valide
- Déclarations fiscales des 2 derniers exercices
- Relevés de compte professionnel des 6 derniers mois

---

## Section 6 — Règles de décision spécifiques crédit consommation

### 6.1 Critères d'approbation automatique (APPROVE)

- PD < 0,35 ET taux d'endettement ≤ 35 % ET aucun incident CR-BCT
- Montant ≤ 20 000 TND ET salarié secteur public ET ancienneté ≥ 2 ans

**Identifiant de règle :** `CONSO-DEC-APPROVE-001`

### 6.2 Critères de renvoi au comité (REFER)

- PD entre 0,35 et 0,65
- Montant > 50 000 TND quelle que soit la PD
- Taux d'endettement entre 36 % et 40 % avec PD < 0,35
- Emprunteur avec classification CR-BCT Classe 2

**Identifiant de règle :** `CONSO-DEC-REFER-001`

### 6.3 Critères de rejet automatique (REJECT)

- Taux d'endettement > 40 %
- PD ≥ 0,65
- Age > 65 ans à la date de demande
- Classification CR-BCT ≥ Classe 3
- Revenu mensuel net < 800 TND
- Moins de 6 mois d'ancienneté dans l'emploi actuel (salarié)

**Identifiant de règle :** `CONSO-DEC-REJECT-001`

---

## Section 7 — Produits associés et cross-selling

### 7.1 Offres complémentaires recommandées

Lors de l'octroi d'un crédit consommation, le conseiller peut proposer :
- **Carte crédit revolving** : limite jusqu'à 5 000 TND, taux à 14,47 %
- **Découvert autorisé** : jusqu'à 1 mensualité de crédit
- **Assurance vie épargne** : pour sécuriser les proches en cas de décès

### 7.2 Programme de fidélité

Les clients remboursant sans incident sur 12 mois consécutifs bénéficient d'une réduction de **0,5 %** sur le taux lors d'un renouvellement ou d'un nouveau crédit.
