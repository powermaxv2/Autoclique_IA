"""Moteur d'Autoclique IA, indépendant de l'interface graphique.

Aucun module de ce paquet n'importe pynput au chargement : les dépendances
système (contrôle de la souris et du clavier, capture d'écran) ne sont
chargées qu'au moment où elles servent, pour que le moteur reste utilisable
et testable sans affichage.
"""
