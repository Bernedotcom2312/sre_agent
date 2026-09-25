
🟠 Bugs fonctionnels

3. get_pod_logs(namespace, pod) filtre sur le container, pas le pod — sre_agent/tools.py:116

Le paramètre s'appelle pod, l'instruction de l'agent dit « If a pod name is known or surfaced by get_k8s_events, call get_pod_logs(namespace, pod) » (sre_agent/agent.py:16)… mais le filtre matche container_name. Or get_k8s_events remonte des noms de pods réels (dummy-app-7d9f8c4b-x2k9p), pas des noms de containers (dummy-app) → zéro log retourné dans le cas d'usage principal. La docstring documente le comportement, mais le LLM suit l'instruction de agent.py, pas la nuance de la docstring.

Le plus robuste : garder un seul paramètre et filtrer sur les deux, (resource.labels.pod_name="X" OR resource.labels.container_name="X").

4. get_k8s_events suppose une forme de payload qu'il ne garantit pas — sre_agent/tools.py:145-156

Le filtre accepte resource.type="k8s_pod", mais le mapping fait entry.payload["reason"] / ["involvedObject"]["name"], ce qui n'est vrai que pour les entrées d'événements Kubernetes. Une entrée k8s_pod qui n'est pas un événement a un payload texte → TypeError: string indices must be integers, non attrapé par handle_gcp_errors (qui ne couvre que DefaultCredentialsError et GoogleAPICallError, tools.py:40-48) → l'outil crashe au lieu de renvoyer un {"error": ...} exploitable par l'agent.

Deux choses à faire : restreindre le filtre aux vrais événements (logName="projects/<id>/logs/events") et utiliser .get() avec valeurs par défaut dans le mapping.

7. Pas d'échappement des arguments injectés dans les filtres

namespace et pod viennent du LLM (donc indirectement de l'utilisateur Slack) et sont interpolés bruts dans les filtres Cloud Logging (tools.py:113-118, 145-149, 186-192). Un " dans la valeur casse le filtre, et on peut y ajouter des clauses. L'impact est limité (API read-only, projet unique), mais une validation type re.fullmatch(r"[a-z0-9-]{1,63}", namespace) est deux lignes et ferme le sujet proprement.

🟡 Slack bot

8. AgentSessions ne survit pas à la réalité de Cloud Run — slack_bot/app.py:61-75

Le mapping thread → session est un dict en mémoire. Trois conséquences :
- --max-instances=2 (script de déploiement) : une requête routée sur l'autre instance recrée une session → le thread perd son contexte de façon aléatoire.
- min-instances=0 : toute mise à l'échelle à zéro efface tout.
- Bolt exécute les listeners dans des threads (app.py:97) : get_or_create n'est pas atomique, deux mentions simultanées dans le même thread peuvent créer deux sessions.

Et le dict ne s'évacue jamais (fuite mémoire lente). Pour un POC c'est défendable, mais ça mérite un commentaire explicite ; la vraie correction est un store externe (Firestore/Redis) ou --max-instances=1 en attendant.

9. Le postmortem markdown va mal s'afficher dans Slack — slack_bot/app.py:133

L'agent produit du markdown standard (## Titre, **gras**) ; Slack utilise mrkdwn (*gras*, pas de titres) et recommande de rester sous ~4000 caractères par message. Un postmortem complet arrivera illisible et potentiellement tronqué. Piste : convertir a minima les titres/gras, ou poster le postmortem en snippet (files_upload_v2).

🟠 Sécurité / cohérence avec la contrainte « read-only »

10. Le service Cloud Run tourne avec le compte de service Compute par défaut — scripts/deploy-slack-bot-cloud-run.sh:71-72

<project-number>-compute@developer.gserviceaccount.com a le rôle Editor sur le projet par défaut. Le bot n'a besoin que d'appeler Agent Engine, et l'agent que de roles/logging.viewer + roles/monitoring.viewer. La garantie « read-only » de CLAUDE.md est aujourd'hui assurée par le code seul ; au niveau IAM, ces identités peuvent tout modifier dans le projet. Créer deux SA dédiés avec les rôles viewer rendrait la contrainte structurelle — ce serait d'ailleurs un excellent point à mettre en avant sur ce projet.

Bon point en revanche : les secrets Slack passent par Secret Manager, pas par --set-env-vars. Et aucun .env n'est suivi par git (vérifié via git ls-files).

🟡 Outillage & docs

11. Aucune CI — pas de .github/. C'est la cause racine du point 1 : les tests sont rouges depuis 9a308b5 sans que rien ne le signale. Sur un projet dont le sujet est DORA/MTTR, un workflow uv sync && uv run pytest && uv run ruff check est presque obligatoire.

12. Dépendances dupliquées en 3 endroits, et déjà désynchronisées : gunicorn==23.0.0 est dans slack_bot/requirements.txt mais absent du groupe slack de pyproject.toml → impossible de reproduire le runtime du conteneur en local. Le commentaire « Keep in sync » (slack_bot/requirements.txt:4) reconnaît le problème sans le résoudre ; la CI peut vérifier la cohérence.

13. todo.md est dans .gitignore alors que README.md et CLAUDE.md pointent tous les deux dessus. Sur un clone frais, deux liens morts. Soit on le versionne, soit on retire les liens.

14. README à corriger : la section « Project structure » décrit slack_bot/app.py comme un front Socket Mode, alors que c'est l'Events API (le reste du README le dit correctement, et app.py:2-4 aussi). L'arbre omet aussi manifests/ et scripts/deploy-slack-bot-cloud-run.sh.

15. uv run ruff format --check échoue sur slack_bot/app.py:125 (un list(...) inutilement éclaté sur 3 lignes). ruff check passe, lui.

🟢 Simplification

Le bloc if not project_id: return {"error": ...} est copié 4 fois à l'identique (tools.py:66-72, 105-111, 133-143, 179-184), soit ~28 lignes dupliquées. Il appartient au décorateur handle_gcp_errors — qui deviendrait d'ailleurs le bon endroit pour attraper aussi KeyError/TypeError (point 4).
