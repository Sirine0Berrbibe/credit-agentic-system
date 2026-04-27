# Circulaire BCT n°2024-03 — Règles d'Octroi de Crédit aux Particuliers

**Émetteur :** Banque Centrale de Tunisie (BCT)  
**Référence :** Circulaire n°2024-03 du 15 mars 2024  
**Objet :** Encadrement des conditions d'octroi de crédit aux particuliers et aux professionnels  
**Applicable à :** Toutes les banques et établissements de crédit agréés en Tunisie

---

## Article 1 — Taux d'endettement maximal

### 1.1 Définition du taux d'endettement

Le taux d'endettement (ratio dette/revenu, DTI — Debt-to-Income) est calculé comme suit :

```
Taux d'endettement = (Total mensualités crédit / Revenu mensuel net) × 100
```

Le revenu mensuel net comprend : salaire net + revenus locatifs réguliers justifiés + pensions alimentaires perçues. Sont exclus : primes exceptionnelles, heures supplémentaires ponctuelles, revenus non récurrents.

### 1.2 Plafonds réglementaires obligatoires

| Catégorie d'emprunteur | Taux d'endettement maximal autorisé |
|------------------------|--------------------------------------|
| Salarié du secteur public (CDI) | **40 %** |
| Salarié du secteur privé (CDI) | **40 %** |
| Salarié du secteur privé (CDD > 1 an) | **35 %** |
| Travailleur indépendant / Professionnel libéral | **33 %** |
| Chef d'entreprise (moins de 3 ans d'activité) | **30 %** |
| Retraité | **35 %** |

**RÈGLE ABSOLUE :** Aucune exception au plafond de 40 % n'est autorisée, quelle que soit la qualité du dossier. Tout dépassement déclenche un rejet automatique (REJECT).

**Identifiant de règle :** `BCT-2024-DTI-001`

### 1.3 Cas particuliers — dérogation encadrée

Une dérogation exceptionnelle jusqu'à **42 %** peut être accordée sous les conditions cumulatives suivantes :
- Revenu mensuel net ≥ 5 000 TND
- Garantie immobilière ou hypothèque de premier rang
- Aucun incident de paiement dans les 24 derniers mois (Centrale des Risques)
- Validation obligatoire par le comité de crédit (human-in-the-loop)

**Identifiant de règle :** `BCT-2024-DTI-002`

---

## Article 2 — Ratio Prêt/Valeur (LTV — Loan-to-Value)

### 2.1 Crédit immobilier

| Type d'opération | LTV maximal |
|------------------|-------------|
| Résidence principale — premier achat | **80 %** |
| Résidence principale — achat ultérieur | **75 %** |
| Résidence secondaire | **70 %** |
| Investissement locatif | **65 %** |
| Terrain nu | **60 %** |

**Identifiant de règle :** `BCT-2024-LTV-001`

### 2.2 Crédit auto

| Type de véhicule | Financement maximal |
|-----------------|---------------------|
| Véhicule neuf | **85 % de la valeur facture** |
| Véhicule d'occasion (< 3 ans) | **75 % de la valeur expertise** |
| Véhicule d'occasion (3–7 ans) | **65 % de la valeur expertise** |
| Véhicule > 7 ans | Non finançable |

**Identifiant de règle :** `BCT-2024-LTV-002`

---

## Article 3 — Durées maximales par produit

| Type de crédit | Durée maximale |
|----------------|----------------|
| Crédit immobilier résidentiel | **25 ans (300 mois)** |
| Crédit immobilier — promoteur agréé BCT | **30 ans (360 mois)** |
| Crédit auto | **7 ans (84 mois)** |
| Crédit consommation | **7 ans (84 mois)** |
| Crédit professionnel court terme | **2 ans (24 mois)** |
| Crédit professionnel moyen terme | **7 ans (84 mois)** |
| Crédit professionnel long terme (investissement) | **15 ans (180 mois)** |

**RÈGLE :** L'échéance finale du crédit ne peut excéder la date à laquelle l'emprunteur atteint **70 ans**. Pour les crédits immobiliers avec assurance décès-invalidité totale, la limite est portée à **75 ans**.

**Identifiant de règle :** `BCT-2024-DUR-001`

---

## Article 4 — Conditions d'éligibilité à l'âge

### 4.1 Âge minimum

L'emprunteur doit être âgé d'au moins **18 ans** à la date de la demande.

**Identifiant de règle :** `BCT-2024-AGE-001`

### 4.2 Âge maximum — crédit immobilier

Pour un crédit immobilier de 25 ans, l'emprunteur ne peut avoir plus de **45 ans** (25 + 45 = 70 ans à l'échéance). En cas de durée réduite, l'âge maximum est calculé dynamiquement : `70 - durée_crédit`.

**Identifiant de règle :** `BCT-2024-AGE-002`

### 4.3 Âge maximum — crédit consommation et auto

L'emprunteur doit avoir moins de **65 ans** à la date de la demande. L'échéance finale ne peut dépasser l'âge de 72 ans.

**Identifiant de règle :** `BCT-2024-AGE-003`

---

## Article 5 — Taux d'intérêt — encadrement légal

### 5.1 Taux de base BCT (TMM)

Le Taux du Marché Monétaire (TMM) en vigueur au 1er janvier 2024 est de **7,97 %**.

### 5.2 Taux effectif global maximal (TEGM)

| Type de crédit | TEGM maximal légal |
|----------------|---------------------|
| Crédit immobilier | TMM + 3 % = **10,97 %** |
| Crédit auto | TMM + 4 % = **11,97 %** |
| Crédit consommation | TMM + 6,5 % = **14,47 %** |
| Crédit professionnel | TMM + 4,5 % = **12,47 %** |

Tout crédit accordé à un taux supérieur au TEGM est nul et expose l'établissement prêteur à des sanctions administratives.

**Identifiant de règle :** `BCT-2024-RATE-001`

---

## Article 6 — Vérification obligatoire de la Centrale des Risques

### 6.1 Obligation de consultation

Avant tout octroi de crédit, l'établissement prêteur est **obligé** de consulter la Centrale des Risques de la BCT pour :
- Connaître l'encours total de crédits de l'emprunteur
- Identifier tout incident de paiement en cours
- Vérifier la classification du client (classe 0 à 5)

**Identifiant de règle :** `BCT-2024-CR-001`

### 6.2 Classification et décision automatique

| Classe Centrale des Risques | Signification | Décision automatique |
|-----------------------------|---------------|----------------------|
| Classe 0 | Aucun crédit déclaré | Éligible |
| Classe 1 | Crédit(s) en cours — remboursement normal | Éligible |
| Classe 2 | Retards < 90 jours (surveiller) | REFER — comité |
| Classe 3 | Retards 90–180 jours (incertain) | REJECT automatique |
| Classe 4 | Retards > 180 jours (préoccupant) | REJECT automatique |
| Classe 5 | Créances irrécouvrables (perte) | REJECT automatique + liste noire |

**Identifiant de règle :** `BCT-2024-CR-002`

---

## Article 7 — Assurances obligatoires

### 7.1 Assurance décès-invalidité totale et permanente (ADIP)

L'assurance ADIP est **obligatoire** pour :
- Tout crédit immobilier, quel que soit le montant
- Tout crédit supérieur à **50 000 TND**

**Identifiant de règle :** `BCT-2024-INS-001`

### 7.2 Assurance chômage

L'assurance chômage est recommandée (non obligatoire) pour tout emprunteur salarié du secteur privé.

### 7.3 Assurance multirisque habitation

Obligatoire pour tout crédit immobilier garantissant un bien immobilier résidentiel. Elle doit être souscrite avant le déblocage des fonds.

**Identifiant de règle :** `BCT-2024-INS-002`

---

## Article 8 — Exigences GDPR et transparence

Conformément aux dispositions du décret-loi n°2022-16 sur la protection des données personnelles, toute décision automatisée de crédit doit :

1. Être accompagnée d'une explication intelligible générée et stockée
2. Permettre à l'emprunteur de demander une révision par un humain
3. Référencer la règle ayant motivé la décision (rule_id)
4. Être consignée dans un journal d'audit immuable (append-only)

**Identifiant de règle :** `BCT-2024-GDPR-001`
