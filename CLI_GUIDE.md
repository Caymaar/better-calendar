# Better Calendar CLI (chub)

CLI pour visualiser les calendriers de jours ouvrés et fériés.

## Installation

```bash
uv pip install -e .
```

## Utilisation

### Syntaxe de base

```bash
chub [OPTIONS] [YEAR] [MONTH]
```

Les jours ouvrés sont affichés normalement, les jours fériés/fermés sont affichés entre `[crochets]`.

### Options

- `-e, --exchange TEXT`: Code MIC de bourse (ex: XPAR, XNYS, XLON)
- `-c, --country TEXT`: Code ISO de pays (ex: FR, US, GB)
- `-r, --rfr TEXT`: Ticker RFR (ex: "ESTRON Index", "SOFRRATE Index")
- `-m, --mode [intersection|union]`: Mode de combinaison (défaut: intersection)

**Note**: Les options peuvent être répétées pour combiner plusieurs calendriers.

## Exemples

### Calendrier simple

```bash
# Calendrier français pour l'année en cours
chub --country FR

# Euronext Paris pour 2026
chub --exchange XPAR 2026

# Mars 2026 pour la France
chub --country FR 2026 3

# €STR (TARGET) pour décembre 2026
chub --rfr "ESTRON Index" 2026 12
```

### Calendriers combinés

#### Mode Intersection (défaut)
Un jour est ouvré **seulement si TOUS** les calendriers sont ouverts.

```bash
# FR + US (intersection) - jour ouvré si France ET USA ouverts
chub -c FR -c US 2026

# Paris + New York
chub -e XPAR -e XNYS 2026 1

# FR + SOFR
chub -c FR -r "SOFRRATE Index" 2026
```

#### Mode Union
Un jour est ouvré **si AU MOINS UN** calendrier est ouvert.

```bash
# Paris OU New York - jour ouvré si l'un des deux est ouvert
chub -e XPAR -e XNYS --mode union 2026

# FR ou US
chub -c FR -c US --mode union 2026 3
```

### Cas d'usage réels

#### Trading international

```bash
# Jours où TOUS les marchés sont ouverts (Paris, NY, Londres)
chub -e XPAR -e XNYS -e XLON --mode intersection 2026

# Jours où AU MOINS UN marché est ouvert
chub -e XPAR -e XNYS -e XLON --mode union 2026
```

#### Équipe distribuée

```bash
# Jours de travail pour équipe France + USA (au moins un pays travaille)
chub -c FR -c US --mode union 2026

# Jours de travail communs (les deux pays travaillent)
chub -c FR -c US --mode intersection 2026
```

#### Fixings de taux

```bash
# Calendrier €STR (TARGET)
chub -r "ESTRON Index" 2026

# Calendrier SOFR (US Gov Bonds)
chub -r "SOFRRATE Index" 2026

# Jours où les deux fixings sont disponibles
chub -r "ESTRON Index" -r "SOFRRATE Index" 2026
```

## Format d'affichage

Le calendrier utilise le format **lundi à dimanche** (Mo → Su) :

```
         March 2026
  Mo  Tu  We  Th  Fr  Sa  Su
                        [ 1]
  2   3   4   5   6 [ 7][ 8]
  9  10  11  12  13 [14][15]
 16  17  18  19  20 [21][22]
 23  24  25  26  27 [28][29]
 30  31 
```

- Jours normaux = jours ouvrés
- `[Jours entre crochets]` = jours fériés / fermés / week-ends

## Exemple de sortie

### Calendrier France + USA (intersection) - Janvier 2026

```bash
$ chub -c FR -c US 2026 1

Calendar: Combined[intersection](Country:FR, Country:US)

        January 2026
  Mo  Tu  We  Th  Fr  Sa  Su
            [ 1]  2 [ 3][ 4]
  5   6   7   8   9 [10][11]
 12  13  14  15  16 [17][18]
[19] 20  21  22  23 [24][25]
 26  27  28  29  30 [31]
```

**Analyse** :
- 1er janvier : Jour de l'an (fermé dans les deux pays)
- 19 janvier : Martin Luther King Jr. Day (USA) → fermé en intersection
- Week-ends : tous entre crochets

## Aide

```bash
chub --help
```
