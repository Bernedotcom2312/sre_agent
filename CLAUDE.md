# SRE Agent — Copilote de diagnostic d'incidents

## Objectif

Réduire le MTTR (métrique DORA) en donnant à un agent la capacité de corréler
alertes, logs et events GKE, puis de proposer un diagnostic et un brouillon
de postmortem. Voir `todo.md` pour le plan détaillé.

## Stack

- **Framework agent** : Google ADK (Agent Development Kit), Python.
- **Sources de données** : Cloud Monitoring (alertes, métriques), Cloud
  Logging, events Kubernetes (`kubectl get events` ou export vers Cloud
  Logging).
- **Déploiement cible** : GKE (tutoriel officiel ADK + GKE) ou Agent Engine.
- **Interface** : `adk web` en local pour le dev ; Slack ou chat web une fois
  déployé.

## Architecture

Agent unique pour le POC (multi-agent via A2A envisageable plus tard pour
séparer "collecte" et "synthèse"). Tous les tools sont en **lecture seule**
(function calling) :

- `get_alerts(time_range)`
- `get_pod_logs(namespace, pod)`
- `get_k8s_events(namespace)`
- `get_recent_deploys(namespace)` — corrélation déploiement → incident

Sortie attendue : résumé structuré (cause probable, timeline, impact) +
brouillon de postmortem en markdown.

## Contraintes importantes

- **Lecture seule** : aucun tool ne doit pouvoir modifier l'état du cluster,
  déclencher un déploiement, ou écrire dans un système externe. L'agent
  diagnostique, il n'agit pas.
- Les credentials GCP/GKE ne doivent jamais être committés ; utiliser
  l'authentification standard (ADC, service account monté) et laisser ces
  fichiers hors du repo.
- Prioriser du code testable en local avec `adk web` avant tout déploiement
  sur GKE/Agent Engine.

## État du projet

Projet à l'état de plan (`todo.md`), aucun code n'a encore été écrit. Pas de
dépôt git initialisé.
