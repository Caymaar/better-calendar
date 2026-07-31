# Notebooks

Six notebooks qui couvrent l'intégralité de l'API publique, chacun autonome et exécutable.
Ils sont commités **avec leurs sorties**, donc lisibles directement sur GitHub sans rien
lancer — et un job CI les ré-exécute pour vérifier qu'ils tournent encore.

| # | Notebook | Contenu |
|---|---|---|
| 01 | [Prise en main](01-prise-en-main.ipynb) | `adjust` / `offset` / `count`, transparence de type, parsing strict, les sept conventions de roll, intervalles, bornes, vectorisation mesurée |
| 02 | [Calendriers et algèbre](02-calendriers-et-algebre.ipynb) | registre, alias, provenance, weekmasks non standard, `& \| - ^` et le piège de vocabulaire, composites, dérivation |
| 03 | [Offsets, tenors et spot](03-offsets-tenors-spot.ipynb) | `BDay` sur scalaires et conteneurs, interop pandas et son écart, accesseur `.cal`, grammaire de tenors, clamping vs règle EOM, lags de règlement |
| 04 | [Récurrences et échéanciers](04-recurrences-et-echeanciers.ipynb) | `nth_weekday` et famille, `n` négatif, occurrences sautées, IMM, expirations, `Schedule` et la séparation non ajusté / ajusté, stubs |
| 05 | [Fuseaux et sessions](05-fuseaux-et-sessions.ipynb) | le bug `.date()`, naïf vs aware, heure murale à travers un changement d'heure, `session_of`, `session_bounds`, `grid` contre le resample mal ancré, `at_times` |
| 06 | [Snapshots et overrides](06-snapshots-et-overrides.ipynb) | pourquoi les données sont figées, format et manifeste, bornes honnêtes, dérive amont, CLI, calendriers d'organisation |

## Lancer

```bash
uv sync --all-extras          # inclut jupyter et les fournisseurs
uv run jupyter lab notebooks/
```

Les notebooks 02 et 06 utilisent les extras fournisseurs pour les parties « dérive » et
« diff » ; tout le reste tourne sur une installation nue.

## Par où commencer

- **Vous découvrez la bibliothèque** : 01, puis 02.
- **Vous faites du pricing ou du back-office** : 03 et 04.
- **Vous manipulez de l'intraday ou du multi-fuseau** : 05, en entier.
- **Vous devez expliquer d'où viennent les données à un auditeur** : 06.

## Note

Ces notebooks ont trouvé deux vrais défauts pendant leur écriture : deux alias pointaient
vers des calendriers absents du snapshot, et neuf devises de la table des lags n'avaient
aucun calendrier de règlement. Les deux sont corrigés, et chacun a désormais un test qui
l'empêche de revenir. Écrire la documentation en l'exécutant, ça sert à ça.
