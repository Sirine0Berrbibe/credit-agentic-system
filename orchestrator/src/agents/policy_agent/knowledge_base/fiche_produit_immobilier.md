# Fiche Produit — Crédit Immobilier Résidentiel

**Établissement :** Amen Bank S.A. (exemple fictif)  
**Produit :** Crédit Immobilier — Résidence Principale et Secondaire  
**Code produit :** IMMO-RES-2024  
**Version :** Janvier 2024

---

## Section 1 — Présentation du produit

### 1.1 Définition

Le crédit immobilier résidentiel est un prêt à moyen et long terme destiné à financer l'acquisition, la construction ou la rénovation d'un bien immobilier à usage d'habitation. Il est garanti par une hypothèque de premier rang sur le bien financé.

### 1.2 Usages éligibles

- Achat d'un logement neuf auprès d'un promoteur immobilier agréé par le Ministère de l'Équipement
- Achat d'un logement ancien (marché secondaire)
- Construction d'une résidence principale sur terrain propriété de l'emprunteur
- Travaux de rénovation ou d'extension sur bien existant (montant minimum : 20 000 TND)
- Rachat de crédit immobilier externe (sous conditions)

---

## Section 2 — Conditions d'éligibilité

### 2.1 Profil emprunteur

| Critère | Condition minimale |
|---------|-------------------|
| Nationalité | Tunisien(ne) résidant en Tunisie |
| Âge minimum | 21 ans à la date de demande |
| Âge maximum | 45 ans (pour un crédit de 25 ans) — règle BCT-2024-AGE-002 |
| Statut professionnel | Salarié CDI (secteur public ou privé) ou indépendant > 3 ans |
| Ancienneté salarié | Minimum 1 an dans l'entreprise actuelle |
| Revenu mensuel net minimum | 2 000 TND (résidence principale), 3 500 TND (résidence secondaire) |
| Taux d'endettement post-crédit | ≤ 40 % (règle BCT-2024-DTI-001) |

**Identifiant de règle :** `IMMO-ELIG-001`

### 2.2 Conditions du bien financé

- Le bien doit être situé sur le territoire tunisien
- Le bien doit être juridiquement libre (aucun litige en cours)
- Titre foncier ou acte de propriété exigé
- Valeur minimale du bien : **30 000 TND**
- Expertise immobilière obligatoire pour les biens > 200 000 TND

---

## Section 3 — Caractéristiques financières

### 3.1 Montants

| Paramètre | Valeur |
|-----------|--------|
| Montant minimum | **20 000 TND** |
| Montant maximum | **500 000 TND** |
| Financement maximal (LTV) | **80 %** de la valeur expertisée (règle BCT-2024-LTV-001) |
| Apport personnel minimum | **20 %** de la valeur du bien |

Pour un bien valorisé à 300 000 TND, le crédit maximum est de 240 000 TND. L'apport minimum est de 60 000 TND.

**Identifiant de règle :** `IMMO-FIN-001`

### 3.2 Durée

| Paramètre | Valeur |
|-----------|--------|
| Durée minimale | 5 ans (60 mois) |
| Durée maximale — standard | 20 ans (240 mois) |
| Durée maximale — promoteur agréé BCT | 25 ans (300 mois) |
| Durée maximale absolue (règle BCT) | Échéance finale avant 70 ans de l'emprunteur |

**Identifiant de règle :** `IMMO-DUR-001`

### 3.3 Taux d'intérêt

| Profil de risque | Taux annuel brut (TAB) | TEGM légal maximal |
|-----------------|------------------------|---------------------|
| Risque faible (PD < 0,35) | TMM + 2,0 % ≈ **9,97 %** | 10,97 % |
| Risque modéré (PD 0,35–0,50) | TMM + 2,5 % ≈ **10,47 %** | 10,97 % |
| Risque élevé (PD > 0,50) | TMM + 3,0 % ≈ **10,97 %** | 10,97 % |

Le taux est fixe pour toute la durée du crédit, sauf option de taux révisable disponible sur demande explicite du client.

---

## Section 4 — Garanties requises

### 4.1 Garantie principale obligatoire

**Hypothèque de premier rang** sur le bien financé, inscrite au registre foncier. L'hypothèque couvre 120 % du montant emprunté.

**Identifiant de règle :** `IMMO-GAR-001`

### 4.2 Garanties complémentaires selon le profil

| Situation | Garantie complémentaire |
|-----------|------------------------|
| LTV > 70 % | Caution personnelle d'un tiers solvable |
| Emprunteur indépendant | Nantissement de fonds de commerce ou assurance crédit |
| Revenu < 2 500 TND/mois | Caution solidaire de conjoint ou co-emprunteur |

---

## Section 5 — Assurances obligatoires

### 5.1 Assurance décès-invalidité totale et permanente (ADIP)

- **Obligatoire** pour tout crédit immobilier (règle BCT-2024-INS-001)
- Taux de cotisation : 0,25 % à 0,45 % du capital restant dû par an selon l'âge
- Couverture : décès toutes causes, invalidité totale et permanente (ITP ≥ 66 %)
- Bénéficiaire : la banque pour le remboursement du solde restant dû

### 5.2 Assurance multirisque habitation

- **Obligatoire** pour tout logement financé (règle BCT-2024-INS-002)
- Doit couvrir : incendie, catastrophes naturelles, responsabilité civile
- Valeur assurée minimale = valeur de reconstruction du bien
- La banque est mentionnée comme bénéficiaire en cas de sinistre

**Identifiant de règle :** `IMMO-ASS-001`

---

## Section 6 — Documents requis

### 6.1 Documents d'identité et de situation

- Copie de la Carte d'Identité Nationale (CIN) valide
- Extrait d'acte de naissance de moins de 6 mois
- Carnet de mariage ou jugement de divorce (si applicable)

### 6.2 Documents de revenus

Pour salarié :
- Attestation de travail de moins de 3 mois
- 3 derniers bulletins de paie
- Relevés bancaires des 3 derniers mois

Pour indépendant :
- Déclarations fiscales des 3 derniers exercices
- Attestation des bénéfices nets établie par un expert-comptable agréé
- Extrait du registre du commerce de moins de 3 mois

### 6.3 Documents du bien

- Titre de propriété ou compromis de vente légalisé
- Attestation de superficie (extrait du plan d'aménagement)
- Rapport d'expertise immobilière (obligatoire pour bien > 200 000 TND)
- Permis de construire (pour construction neuve)

---

## Section 7 — Règles de décision spécifiques au crédit immobilier

### 7.1 Critères d'approbation automatique (APPROVE)

- PD < 0,35 ET taux endettement ≤ 33 % ET LTV ≤ 70 % ET aucun incident CR-BCT
- Revenu ≥ 3 000 TND/mois ET ancienneté ≥ 3 ans ET apport ≥ 25 %

**Identifiant de règle :** `IMMO-DEC-APPROVE-001`

### 7.2 Critères de renvoi au comité (REFER)

- PD entre 0,35 et 0,65 (zone grise)
- LTV entre 70 % et 80 % avec PD entre 0,20 et 0,35
- Emprunteur indépendant avec revenu variable
- Montant > 300 000 TND

**Identifiant de règle :** `IMMO-DEC-REFER-001`

### 7.3 Critères de rejet automatique (REJECT)

- Taux d'endettement > 40 % après intégration du nouveau crédit
- LTV > 80 %
- Âge à l'échéance > 70 ans
- PD > 0,65
- Classification CR-BCT ≥ Classe 3
- Apport personnel < 20 %

**Identifiant de règle :** `IMMO-DEC-REJECT-001`
