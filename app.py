from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import googlemaps
import os
import time
import json
import math
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

app = Flask(__name__)

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', 'AIzaSyAI-VXfNrlF7RmK9ED7Eo6_FMfxYWyE-nU')
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY) if GOOGLE_MAPS_API_KEY != 'VOTRE_CLE_API_ICI' else None

CHUNK_SIZE = 20
CACHE_FILE = 'distances_cache.json'

# =============================================================================
# REGLES METIER
#
#   Livraison  : site -> livraison -> (collecte | debut_transit | site)
#   Collecte   : (site | fin_transit | livraison) -> collecte -> site
#   Transit    : (site | livraison) -> debut_transit -> fin_transit
#                                   -> (site | collecte | debut_transit)
#   Boucle     : Transporteur -> Site -> [atomes] -> Site -> Transporteur
#
# Un atome est un chemin complet Site -> ... -> Site.
# La tournee est une sequence d'atomes independants.
#
# Les atomes sont construits DYNAMIQUEMENT (pas de pre-generation)
# pour eviter l'explosion combinatoire N! avec N transits.
# =============================================================================

# ==================== VALIDATION ====================

def valider_collecte(c):
    return bool(c.get('adresse', '').strip()) and bool(c.get('client', '').strip())

def valider_livraison(l):
    return bool(l.get('adresse', '').strip()) and bool(l.get('client', '').strip())

def valider_transit(t):
    return (bool(t.get('adresse_depart', '').strip()) and
            bool(t.get('adresse_arrivee', '').strip()) and
            bool(t.get('matiere_transit', '').strip()))

def valider_transporteur(t):
    return (bool(t.get('adresse', '').strip()) and
            bool(t.get('client', '').strip()) and
            bool(t.get('ID_transporteur', '').strip()))

def filtrer_donnees(collectes, livraisons, transits, transporteurs):
    cv = [c for c in collectes if valider_collecte(c)]
    lv = [l for l in livraisons if valider_livraison(l)]
    tv = [t for t in transits if valider_transit(t)]
    trv = [t for t in transporteurs if valider_transporteur(t)]
    print(f"\nFiltrage: collectes {len(collectes)}->{len(cv)}, "
          f"livraisons {len(livraisons)}->{len(lv)}, "
          f"transits {len(transits)}->{len(tv)}, "
          f"transporteurs {len(transporteurs)}->{len(trv)}")
    return cv, lv, tv, trv

# ==================== ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "OK",
        "message": "API operationnelle",
        "google_maps_configured": gmaps is not None
    })

@app.route('/optimize', methods=['POST'])
def optimize_route():
    try:
        data = request.json
        collectes    = data.get('collectes', [])
        livraisons   = data.get('livraisons', [])
        transits     = data.get('Transits', [])
        transporteurs = data.get('Transporteurs', [])
        site         = data.get('site_traitement', {})
        contraintes  = data.get('contraintes', {})

        collectes, livraisons, transits, transporteurs = filtrer_donnees(
            collectes, livraisons, transits, transporteurs)

        if not transporteurs:
            return jsonify({"error": "Aucun transporteur valide"}), 400
        if not collectes and not livraisons and not transits:
            return jsonify({"error": "Aucun trajet valide"}), 400

        solution = optimize_with_transporteurs(
            collectes, livraisons, transits, transporteurs, site, contraintes)
        return jsonify(solution)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 400

# ==================== OPTIMISATION PRINCIPALE ====================

def optimize_with_transporteurs(collectes, livraisons, transits, transporteurs, site, contraintes):
    solutions = []

    for transporteur in transporteurs:
        print(f"\n{'='*60}")
        print(f"Transporteur: {transporteur['client']} ({transporteur['ID_transporteur']})")

        collectes_ok  = []
        collectes_nok = []
        for c in collectes:
            imp = c.get('transporteur', '').strip()
            if imp == '' or imp == transporteur['ID_transporteur']:
                collectes_ok.append(c)
            else:
                collectes_nok.append(c)
                print(f"  Collecte {c.get('ID_entree','?')} incompatible (impose {imp})")

        sol = calculate_route_with_transporteur(
            collectes_ok, livraisons, transits, transporteur, site, contraintes)

        if sol.get('success'):
            # Ajouter collectes incompatibles aux non-inclus
            if collectes_nok:
                sol.setdefault('trajets_non_inclus', [])
                for c in collectes_nok:
                    sol['trajets_non_inclus'].append({
                        'type': 'collecte',
                        'ID_entree': c.get('ID_entree', ''),
                        'client': c.get('client', ''),
                        'raison': f"Transporteur incompatible (impose {c.get('transporteur','')})"
                    })
                nb_total = len(collectes) + len(livraisons) + len(transits)
                nb_inclus = nb_total - len(sol['trajets_non_inclus'])
                sol['statistiques']['taux_completion'] = (
                    f"{nb_inclus/nb_total*100:.0f}%" if nb_total > 0 else "0%")

            solutions.append({'transporteur': transporteur, 'solution': sol})

    if not solutions:
        return {"error": "Aucune solution trouvee"}

    def score(s):
        st = s['solution']['statistiques']
        return (st['nombre_collectes_incluses'] +
                st['nombre_livraisons_incluses'] +
                st['nombre_transits_inclus'],
                -st['distance_totale_km'],
                -st['duree_totale_heures'])

    meilleure = max(solutions, key=score)
    result = meilleure['solution']
    result['transporteur_optimal'] = {
        'ID_transporteur': meilleure['transporteur']['ID_transporteur'],
        'nom': meilleure['transporteur']['client'],
        'adresse': meilleure['transporteur']['adresse']
    }

    if len(solutions) > 1:
        comparaisons = []
        for s in solutions:
            if s['transporteur']['ID_transporteur'] != meilleure['transporteur']['ID_transporteur']:
                st = s['solution']['statistiques']
                comparaisons.append({
                    'ID_transporteur': s['transporteur']['ID_transporteur'],
                    'nom': s['transporteur']['client'],
                    'distance_km': st['distance_totale_km'],
                    'duree_heures': st['duree_totale_heures'],
                    'trajets_couverts': (st['nombre_collectes_incluses'] +
                                        st['nombre_livraisons_incluses'] +
                                        st['nombre_transits_inclus'])
                })
        result['transporteurs_alternatifs'] = comparaisons

    return result

# ==================== CALCUL DE ROUTE ====================

def calculate_route_with_transporteur(collectes, livraisons, transits, transporteur, site, contraintes):
    # Index fixes : 0 = transporteur, 1 = site
    locations    = [transporteur['adresse'], site['adresse']]
    location_info = [
        {'type': 'transporteur', 'nom': transporteur['client'],
         'adresse': transporteur['adresse'],
         'ID_transporteur': transporteur['ID_transporteur']},
        {'type': 'site', 'nom': site.get('nom', 'Site'), 'adresse': site['adresse']}
    ]

    collecte_indices  = []
    livraison_indices = []
    transit_indices   = []  # liste de (depart_idx, arrivee_idx)

    for c in collectes:
        locations.append(c['adresse'])
        collecte_indices.append(len(locations) - 1)
        location_info.append({
            'type': 'collecte', 'nom': c['client'], 'adresse': c['adresse'],
            'ID_entree': c.get('ID_entree', ''),
            'date_fixe': c.get('date_fixe', ''),
            'date_flexible_debut': c.get('date_flexible_debut', ''),
            'date_flexible_fin': c.get('date_flexible_fin', ''),
            'transporteur': c.get('transporteur', '')
        })

    for l in livraisons:
        locations.append(l['adresse'])
        livraison_indices.append(len(locations) - 1)
        location_info.append({
            'type': 'livraison', 'nom': l['client'], 'adresse': l['adresse'],
            'ID_sortie': l.get('ID_sortie', ''),
            'date_fixe': l.get('date_fixe', ''),
            'date_flexible_debut': l.get('date_flexible_debut', ''),
            'date_flexible_fin': l.get('date_flexible_fin', '')
        })

    for idx, t in enumerate(transits):
        locations.append(t['adresse_depart'])
        dep_idx = len(locations) - 1
        location_info.append({
            'type': 'transit_depart', 'nom': f"Transit chargement ({t.get('matiere_transit','')})",
            'adresse': t['adresse_depart'],
            'ID_transit': t.get('ID_transit', ''),
            'matiere': t.get('matiere_transit', ''),
            'date_fixe': t.get('date_fixe', ''),
            'date_flexible_debut': t.get('date_flexible_debut', ''),
            'date_flexible_fin': t.get('date_flexible_fin', ''),
            'transit_id': idx
        })
        locations.append(t['adresse_arrivee'])
        arr_idx = len(locations) - 1
        location_info.append({
            'type': 'transit_arrivee', 'nom': f"Transit livraison ({t.get('matiere_transit','')})",
            'adresse': t['adresse_arrivee'],
            'ID_transit': t.get('ID_transit', ''),
            'matiere': t.get('matiere_transit', ''),
            'date_fixe': t.get('date_fixe', ''),
            'date_flexible_debut': t.get('date_flexible_debut', ''),
            'date_flexible_fin': t.get('date_flexible_fin', ''),
            'transit_id': idx
        })
        transit_indices.append((dep_idx, arr_idx))

    print(f"  Lieux: {len(locations)} "
          f"(col={len(collecte_indices)}, liv={len(livraison_indices)}, transit={len(transit_indices)})")

    # Contraintes
    duree_max             = None
    vitesse_moyenne       = 70.0
    temps_operation_min   = 30.0

    if contraintes:
        try: duree_max = float(contraintes['duree_max_en_heure'])
        except: pass
        try: vitesse_moyenne = float(contraintes['vitesse_moyenne_kmh'])
        except: pass
        try: temps_operation_min = float(contraintes['temps_operation_minutes'])
        except: pass

    params = {
        'vitesse_moyenne_kmh': vitesse_moyenne,
        'temps_operation_heures': temps_operation_min / 60.0
    }

    print(f"  Contraintes: duree_max={duree_max}h, vitesse={vitesse_moyenne}km/h, "
          f"op={temps_operation_min}min")

    distance_matrix = get_distance_matrix(locations)

    # Recherche de la meilleure solution par date (atomes construits dynamiquement)
    solution = find_best_solution(
        collecte_indices, livraison_indices, transit_indices,
        location_info, distance_matrix, duree_max, transporteur, params)

    return solution

# ==================== CONSTRUCTION DYNAMIQUE DES ATOMES ====================
#
# Principe : on ne pre-genere pas les atomes. A chaque etape de la boucle
# gloutonne, on construit l'atome courant decision par decision :
#
#   ETAPE 1 - Debut d'atome (depuis le site) :
#     a) Choisir une livraison   -> S -> Liv -> [suite]
#     b) Choisir un transit      -> S -> DebT -> FinT -> [suite]
#     c) Choisir une collecte    -> S -> Col -> S  (atome complet)
#
#   ETAPE 2 - Suite apres livraison ou fin_transit :
#     a) Terminer au site        -> ... -> S
#     b) Ajouter une collecte    -> ... -> Col -> S
#     c) Ajouter un transit      -> ... -> DebT -> FinT -> [suite] (recurse)
#
# A chaque decision on evalue le score de chaque option et on choisit
# la meilleure. L'atome est ferme quand on revient au site.
#
# Complexite : O(N_trajets^2) au lieu de O(N_transits!)

# ==================== CONSTRUCTION ITERATIVE DES ATOMES ====================
#
# On abandonne toute recursion. La tournee est construite en etendant
# l'atome courant noeud par noeud dans une boucle while.
#
# Etat courant d'un atome en construction :
#   - pos       : position actuelle (index dans location_info)
#   - arrets    : liste des arrets deja visites
#   - dist      : distance accumulee
#   - nb_op     : nb d'operations accumulees
#   - transits_dans_atome : set des transit_id deja utilises dans cet atome
#   - a_livraison : bool (une livraison a deja ete faite dans cet atome)
#
# A chaque iteration on choisit parmi :
#   1. Fermer l'atome au site (-> S)
#   2. Ajouter une collecte et fermer (-> Col -> S)
#   3. Ajouter un transit (-> DebT -> FinT) et continuer
#   + si atome vide : commencer par une livraison (S -> Liv)
#     ou un transit  (S -> DebT -> FinT)
#
# Critere de choix a chaque etape :
#   - Priorite 1 : maximiser le nombre de trajets couverts dans l'atome
#   - Priorite 2 : minimiser la distance
#
# Complexite : O(N_trajets * N_transits) par atome, O(N_trajets^2) total.

def find_best_solution(collecte_indices, livraison_indices, transit_indices,
                       location_info, distance_matrix, duree_max_heures,
                       transporteur, params):
    V  = params['vitesse_moyenne_kmh']
    OP = params['temps_operation_heures']

    dates_possibles = set()
    for idx in collecte_indices + livraison_indices:
        ajouter_dates(location_info[idx], dates_possibles)
    for (dep, arr) in transit_indices:
        ajouter_dates(location_info[dep], dates_possibles)

    if not dates_possibles:
        return {"error": "Aucune date possible",
                "details": "Aucune contrainte de date definie"}

    dates_possibles = sorted(dates_possibles)
    print(f"  {len(dates_possibles)} dates candidates")

    meilleures = []
    for date in dates_possibles:
        print(f"  Test date: {date.strftime('%d/%m/%Y')}")
        sol = construire_sequence_gloutonne(
            collecte_indices, livraison_indices, transit_indices,
            location_info, distance_matrix, duree_max_heures,
            date, V, OP)
        if sol:
            meilleures.append(sol)
            print(f"    -> {sol['nb_trajets_couverts']} trajets, "
                  f"{sol['duree_totale']:.1f}h, "
                  f"{sol['distance_totale']/1000:.0f}km")

    if not meilleures:
        return {"error": "Aucune solution trouvee",
                "details": "Aucune date ne satisfait les contraintes"}

    optimale = max(meilleures,
                   key=lambda x: (x['nb_trajets_couverts'],
                                  -x['duree_totale'],
                                  -x['distance_totale']))

    return formater_solution_finale(
        optimale, location_info,
        collecte_indices, livraison_indices, transit_indices)


def ajouter_dates(info, dates_possibles):
    date_fixe = info.get('date_fixe', '')
    if date_fixe and date_fixe.strip():
        try:
            dates_possibles.add(datetime.strptime(date_fixe.strip(), '%Y-%m-%d'))
        except: pass
    debut = info.get('date_flexible_debut', '')
    fin   = info.get('date_flexible_fin', '')
    if debut and fin and debut.strip() and fin.strip():
        try:
            d = datetime.strptime(debut.strip(), '%Y-%m-%d')
            f = datetime.strptime(fin.strip(), '%Y-%m-%d')
            while d <= f:
                dates_possibles.add(d)
                d += timedelta(days=1)
        except: pass


def date_compatible(info, date_candidate):
    date_fixe = info.get('date_fixe', '')
    if date_fixe and date_fixe.strip():
        try:
            return datetime.strptime(date_fixe.strip(), '%Y-%m-%d') == date_candidate
        except: pass
    debut = info.get('date_flexible_debut', '')
    fin   = info.get('date_flexible_fin', '')
    if debut and fin and debut.strip() and fin.strip():
        try:
            d = datetime.strptime(debut.strip(), '%Y-%m-%d')
            f = datetime.strptime(fin.strip(), '%Y-%m-%d')
            return d <= date_candidate <= f
        except: pass
    return True


def construire_sequence_gloutonne(
        collecte_indices, livraison_indices, transit_indices,
        location_info, dm, duree_max_heures, date_candidate, V, OP):
    """
    Construit la tournee complete pour une date donnee.
    Boucle : Transporteur(0) -> Site(1) -> [atomes] -> Site(1) -> Transporteur(0)
    Chaque atome est construit iterativement, sans recursion.
    """
    S = 1

    livraisons_restantes = set(livraison_indices)
    collectes_restantes  = set(collecte_indices)
    transits_restants    = set(range(len(transit_indices)))

    d_aller  = dm[0][S]
    d_retour = dm[S][0]
    overhead_aller_retour = (d_aller + d_retour) / 1000.0 / V

    sequence_atomes = []
    duree_atomes    = 0.0
    distance_atomes = 0.0

    MAX_ATOMES = 500
    for _ in range(MAX_ATOMES):
        if not livraisons_restantes and not collectes_restantes and not transits_restants:
            break

        budget_restant = (duree_max_heures - overhead_aller_retour - duree_atomes
                          if duree_max_heures is not None else None)

        atome = _construire_un_atome(
            S,
            livraisons_restantes, collectes_restantes, transits_restants,
            transit_indices, location_info, dm, V, OP,
            budget_restant, date_candidate)

        if atome is None:
            break

        sequence_atomes.append(atome)
        duree_atomes    += atome['duree_heures']
        distance_atomes += atome['distance']

        for l in atome['livraisons']:  livraisons_restantes.discard(l)
        for c in atome['collectes']:   collectes_restantes.discard(c)
        for t in atome['transits']:    transits_restants.discard(t)

    if not sequence_atomes:
        return None

    nb_trajets = (len(collecte_indices)  - len(collectes_restantes) +
                  len(livraison_indices) - len(livraisons_restantes) +
                  len(transit_indices)   - len(transits_restants))

    return {
        'date': date_candidate,
        'sequence_atomes': sequence_atomes,
        'nb_trajets_couverts': nb_trajets,
        'duree_totale': duree_atomes + overhead_aller_retour,
        'distance_totale': distance_atomes + d_aller + d_retour,
        'collectes_restantes': collectes_restantes,
        'livraisons_restantes': livraisons_restantes,
        'transits_restants': transits_restants,
        'duree_max_heures': duree_max_heures
    }


def _construire_un_atome(S, livraisons_restantes, collectes_restantes,
                          transits_restants, transit_indices,
                          location_info, dm, V, OP, budget_restant, date_candidate):
    """
    Construit UN atome complet Site->...->Site de facon iterative.

    Regles metier respectees :
      - Livraison  : site → livraison → (collecte | debut_transit | site)
      - Collecte   : (site | fin_transit | livraison) → collecte → site
      - Transit    : (site | livraison) → debut_transit → fin_transit
                     → (site | collecte | debut_transit)

    L'atome stocke toujours ses arrets avec S en tete et S en queue :
      arrets = [S, noeud1, noeud2, ..., S]
    """
    pos                 = S
    arrets              = [S]       # inclut le S initial
    dist                = 0.0
    nb_op               = 0
    transits_dans_atome = set()
    a_livraison         = False
    livraisons_atome    = []
    collectes_atome     = []
    transits_atome      = []

    # Type du dernier noeud utile (pour valider les transitions)
    # 'site' | 'livraison' | 'fin_transit'
    type_pos = 'site'

    MAX_NOEUDS = 200
    for _ in range(MAX_NOEUDS):

        # ================================================================
        # Options de fermeture (toujours evaluees)
        # ================================================================
        meilleures_fermetures = []

        # La fermeture directe au site est possible depuis :
        #   site (atome vide -> invalide), livraison, fin_transit
        # Un atome vide (arrets == [S]) n'est pas valide.
        if len(arrets) > 1:

            # Fermer au site directement
            d_fermer = dm[pos][S]
            duree_fermer = (dist + d_fermer) / 1000.0 / V + nb_op * OP
            if budget_restant is None or duree_fermer <= budget_restant:
                nb = len(livraisons_atome) + len(collectes_atome) + len(transits_atome)
                meilleures_fermetures.append({
                    'score': (-nb, dist + d_fermer),
                    'type': 'fermer',
                    'dist_finale': dist + d_fermer,
                    'duree_finale': duree_fermer,
                    'arrets_finaux': arrets + [S],
                })

            # Fermer via une collecte -> site
            # Autorise depuis : livraison, fin_transit, (et site si atome non vide)
            if type_pos in ('livraison', 'fin_transit', 'site') and len(arrets) > 1:
                for col in collectes_restantes:
                    if col in collectes_atome:
                        continue
                    if not date_compatible(location_info[col], date_candidate):
                        continue
                    d_col = dm[pos][col] + dm[col][S]
                    duree_col = (dist + d_col) / 1000.0 / V + (nb_op + 1) * OP
                    if budget_restant is None or duree_col <= budget_restant:
                        nb = (len(livraisons_atome) + len(collectes_atome) + 1 +
                              len(transits_atome))
                        meilleures_fermetures.append({
                            'score': (-nb, dist + d_col),
                            'type': 'fermer_col',
                            'col': col,
                            'dist_finale': dist + d_col,
                            'duree_finale': duree_col,
                            'arrets_finaux': arrets + [col, S],
                        })

        # ================================================================
        # Options d'extension (selon les regles metier)
        # ================================================================
        extensions = []

        # -- Livraison : uniquement depuis site, en debut d'atome --
        # site → livraison
        if type_pos == 'site' and len(arrets) == 1 and not a_livraison:
            for liv in livraisons_restantes:
                if not date_compatible(location_info[liv], date_candidate):
                    continue
                d_liv = dm[S][liv]
                duree_min = (d_liv + dm[liv][S]) / 1000.0 / V + OP
                if budget_restant is None or duree_min <= budget_restant:
                    extensions.append({
                        'type': 'livraison',
                        'idx': liv,
                        'gain': 1,
                        'dist_ajout': d_liv,
                    })

        # -- Transit : depuis site ou livraison --
        # site → debut_transit  OU  livraison → debut_transit
        # OU  fin_transit → debut_transit  (enchaînement)
        if type_pos in ('site', 'livraison', 'fin_transit'):
            for tid in transits_restants:
                if tid in transits_dans_atome:
                    continue
                dep_idx, arr_idx = transit_indices[tid]
                if not date_compatible(location_info[dep_idx], date_candidate):
                    continue
                d_tr = dm[pos][dep_idx] + dm[dep_idx][arr_idx]
                duree_min = (dist + d_tr + dm[arr_idx][S]) / 1000.0 / V + (nb_op + 2) * OP
                if budget_restant is None or duree_min <= budget_restant:
                    extensions.append({
                        'type': 'transit',
                        'tid': tid,
                        'dep': dep_idx,
                        'arr': arr_idx,
                        'gain': 1,
                        'dist_ajout': d_tr,
                    })

        # ================================================================
        # Decision
        # ================================================================
        if not extensions:
            # Plus rien a etendre : fermer si possible
            if meilleures_fermetures:
                meilleures_fermetures.sort(key=lambda x: x['score'])
                f = meilleures_fermetures[0]
                return _finaliser_atome(f, livraisons_atome, collectes_atome,
                                        transits_atome, f['dist_finale'], f['duree_finale'])
            return None

        meilleure_fermeture = None
        if meilleures_fermetures:
            meilleures_fermetures.sort(key=lambda x: x['score'])
            meilleure_fermeture = meilleures_fermetures[0]

        nb_actuel = len(livraisons_atome) + len(collectes_atome) + len(transits_atome)
        extensions.sort(key=lambda x: (-x['gain'], x['dist_ajout']))
        meilleure_ext = extensions[0]

        nb_si_extension = nb_actuel + meilleure_ext['gain']
        nb_si_fermeture = -meilleure_fermeture['score'][0] if meilleure_fermeture else 0

        # Etendre si l'extension couvre plus de trajets, ou si l'atome est encore vide
        if nb_si_extension <= nb_si_fermeture and nb_actuel > 0:
            f = meilleure_fermeture
            return _finaliser_atome(f, livraisons_atome, collectes_atome,
                                    transits_atome, f['dist_finale'], f['duree_finale'])

        # Appliquer l'extension
        ext = meilleure_ext
        if ext['type'] == 'livraison':
            liv = ext['idx']
            dist += dm[S][liv]
            nb_op += 1
            arrets.append(liv)
            livraisons_atome.append(liv)
            a_livraison = True
            pos = liv
            type_pos = 'livraison'

        elif ext['type'] == 'transit':
            tid = ext['tid']
            dep = ext['dep']
            arr = ext['arr']
            dist += dm[pos][dep] + dm[dep][arr]
            nb_op += 2
            arrets += [dep, arr]
            transits_dans_atome.add(tid)
            transits_atome.append(tid)
            pos = arr
            type_pos = 'fin_transit'

    # Garde-fou : fermer si possible
    if len(arrets) > 1 and meilleures_fermetures:
        meilleures_fermetures.sort(key=lambda x: x['score'])
        f = meilleures_fermetures[0]
        return _finaliser_atome(f, livraisons_atome, collectes_atome,
                                transits_atome, f['dist_finale'], f['duree_finale'])
    return None


def _finaliser_atome(fermeture, livraisons_atome, collectes_atome, transits_atome,
                     dist_finale, duree_finale):
    """Construit le dict atome final depuis une option de fermeture."""
    if fermeture['type'] == 'fermer_col':
        col = fermeture['col']
        collectes_finales = collectes_atome + [col]
    else:
        collectes_finales = list(collectes_atome)

    nb = len(livraisons_atome) + len(collectes_finales) + len(transits_atome)
    return {
        'arrets': fermeture['arrets_finaux'],
        'distance': dist_finale,
        'duree_heures': duree_finale,
        'nb_trajets': nb,
        'livraisons': list(livraisons_atome),
        'collectes': collectes_finales,
        'transits': list(transits_atome),
    }

# ==================== FORMATAGE ====================

def formater_solution_finale(solution, location_info,
                              collecte_indices, livraison_indices, transit_indices):
    date_str = solution['date'].strftime('%Y-%m-%d')
    date_fmt = solution['date'].strftime('%d/%m/%Y')
    info_tr   = location_info[0]
    info_site = location_info[1]
    itineraire = []
    ordre = 1

    itineraire.append({
        'ordre': ordre, 'phase': 0, 'type': 'depart_transporteur',
        'client': info_tr['nom'], 'adresse': info_tr['adresse'],
        'ID_transporteur': info_tr.get('ID_transporteur', ''),
        'date_prevue': date_str
    }); ordre += 1

    nb_atomes = len(solution['sequence_atomes'])
    for phase_num, atome in enumerate(solution['sequence_atomes'], start=1):
        # Afficher le site en debut d'atome (= arrets[0] = S)
        # Pour le 1er atome c'est l'arrivee sur site depuis le transporteur,
        # pour les suivants c'est un passage site (deja affiche en fin du precedent).
        if phase_num == 1:
            itineraire.append({
                'ordre': ordre, 'phase': phase_num, 'type': 'arrivee_site',
                'client': info_site['nom'], 'adresse': info_site['adresse'],
                'date_prevue': date_str
            }); ordre += 1

        # Arrêts internes (tout sauf S initial et S final)
        for idx in atome['arrets'][1:-1]:
            info = location_info[idx]
            t    = info['type']
            if t == 'livraison':
                arret = {'ordre': ordre, 'phase': phase_num, 'type': 'livraison',
                         'client': info['nom'], 'adresse': info['adresse'],
                         'ID_sortie': info.get('ID_sortie', ''), 'date_prevue': date_str}
            elif t == 'collecte':
                arret = {'ordre': ordre, 'phase': phase_num, 'type': 'collecte',
                         'client': info['nom'], 'adresse': info['adresse'],
                         'ID_entree': info.get('ID_entree', ''), 'date_prevue': date_str}
            elif t == 'transit_depart':
                arret = {'ordre': ordre, 'phase': phase_num, 'type': 'transit_chargement',
                         'client': info['nom'], 'adresse': info['adresse'],
                         'ID_transit': info.get('ID_transit', ''),
                         'matiere': info.get('matiere', ''), 'date_prevue': date_str}
            elif t == 'transit_arrivee':
                arret = {'ordre': ordre, 'phase': phase_num, 'type': 'transit_livraison',
                         'client': info['nom'], 'adresse': info['adresse'],
                         'ID_transit': info.get('ID_transit', ''),
                         'matiere': info.get('matiere', ''), 'date_prevue': date_str}
            else:
                arret = {'ordre': ordre, 'phase': phase_num, 'type': t,
                         'client': info['nom'], 'adresse': info['adresse'],
                         'date_prevue': date_str}
            itineraire.append(arret); ordre += 1

        # Passage site apres cet atome, sauf apres le dernier
        # (le dernier atome se termine au site, d'ou repart le transporteur)
        if phase_num < nb_atomes:
            itineraire.append({
                'ordre': ordre, 'phase': phase_num, 'type': 'passage_site',
                'client': info_site['nom'], 'adresse': info_site['adresse'],
                'date_prevue': date_str
            }); ordre += 1

    itineraire.append({
        'ordre': ordre, 'phase': nb_atomes + 1,
        'type': 'retour_transporteur',
        'client': info_tr['nom'], 'adresse': info_tr['adresse'],
        'ID_transporteur': info_tr.get('ID_transporteur', ''),
        'date_prevue': date_str
    })

    trajets_non_inclus = []
    for idx in solution['collectes_restantes']:
        trajets_non_inclus.append({'type': 'collecte',
            'ID_entree': location_info[idx].get('ID_entree', ''),
            'client': location_info[idx]['nom'],
            'raison': 'Contrainte de duree ou date incompatible'})
    for idx in solution['livraisons_restantes']:
        trajets_non_inclus.append({'type': 'livraison',
            'ID_sortie': location_info[idx].get('ID_sortie', ''),
            'client': location_info[idx]['nom'],
            'raison': 'Contrainte de duree ou date incompatible'})
    for tid in solution['transits_restants']:
        dep_idx, _ = transit_indices[tid]
        trajets_non_inclus.append({'type': 'transit',
            'ID_transit': location_info[dep_idx].get('ID_transit', ''),
            'matiere': location_info[dep_idx].get('matiere', ''),
            'raison': 'Contrainte de duree ou date incompatible'})

    nb_total  = len(collecte_indices) + len(livraison_indices) + len(transit_indices)
    nb_inclus = solution['nb_trajets_couverts']

    result = {
        'success': True,
        'solution_complete': len(trajets_non_inclus) == 0,
        'date_optimale': date_str,
        'date_optimale_formatee': date_fmt,
        'itineraire': itineraire,
        'nombre_atomes': len(solution['sequence_atomes']),
        'statistiques': {
            'distance_totale_km': round(solution['distance_totale'] / 1000, 2),
            'duree_totale_heures': round(solution['duree_totale'], 2),
            'duree_max_autorisee_heures': solution.get('duree_max_heures'),
            'cout_estime_euros': round(solution['distance_totale'] / 1000 * 1.5, 2),
            'nombre_collectes_incluses': len(collecte_indices) - len(solution['collectes_restantes']),
            'nombre_collectes_totales': len(collecte_indices),
            'nombre_livraisons_incluses': len(livraison_indices) - len(solution['livraisons_restantes']),
            'nombre_livraisons_totales': len(livraison_indices),
            'nombre_transits_inclus': len(transit_indices) - len(solution['transits_restants']),
            'nombre_transits_totaux': len(transit_indices),
            'taux_completion': f"{nb_inclus/nb_total*100:.0f}%" if nb_total > 0 else "0%"
        },
        'explication': {
            'methode': 'Glouton iteratif sans recursion - O(N^2)',
            'date_choisie_raison': f"Couvre {nb_inclus}/{nb_total} trajets"
        }
    }
    if trajets_non_inclus:
        result['trajets_non_inclus'] = trajets_non_inclus
        result['avertissement'] = f"{len(trajets_non_inclus)} trajet(s) non inclus"
    return result

# ==================== DISTANCES ====================

def load_distances_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                print(f"   Cache charge ({len(cache)} entrees)")
                return cache
    except Exception as e:
        print(f"   Erreur cache: {e}")
    return {}

def save_distances_cache(cache):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"   Erreur sauvegarde cache: {e}")

def get_cache_key(origin, destination):
    try:
        return f"{str(origin).strip().lower()}|{str(destination).strip().lower()}"
    except:
        return None

def get_distance_matrix(locations):
    n = len(locations)
    distance_matrix = [[0.0] * n for _ in range(n)]

    if n <= 1:
        return distance_matrix

    if gmaps is None:
        return _estimate_distance_matrix(locations)

    cache = load_distances_cache()

    if n <= 25:
        return _get_distance_matrix_simple(locations, distance_matrix, cache)
    return _get_distance_matrix_chunked(locations, distance_matrix, cache)

def _get_distance_matrix_simple(locations, distance_matrix, cache):
    n = len(locations)

    all_cached = True
    for i in range(n):
        for j in range(n):
            if i == j:
                distance_matrix[i][j] = 0.0
                continue
            key = get_cache_key(locations[i], locations[j])
            if key and key in cache:
                try:
                    distance_matrix[i][j] = float(cache[key]['distance_m'])
                except:
                    all_cached = False
            else:
                all_cached = False

    if all_cached:
        return distance_matrix

    try:
        result = gmaps.distance_matrix(
            origins=locations, destinations=locations,
            mode='driving', units='metric')

        if result['status'] != 'OK':
            return _estimate_distance_matrix(locations)

        for i in range(n):
            for j in range(n):
                try:
                    el = result['rows'][i]['elements'][j]
                    if el['status'] == 'OK':
                        d = float(el['distance']['value'])
                        distance_matrix[i][j] = max(0.0, d)
                        key = get_cache_key(locations[i], locations[j])
                        if key:
                            cache[key] = {
                                'distance_m': d,
                                'duration_s': float(el['duration']['value']),
                                'cached_at': datetime.now().isoformat()
                            }
                    else:
                        distance_matrix[i][j] = 100000.0
                except:
                    distance_matrix[i][j] = 100000.0

        save_distances_cache(cache)
        return distance_matrix

    except Exception as e:
        print(f"Erreur Google Maps: {e}")
        return _estimate_distance_matrix(locations)

def _get_distance_matrix_chunked(locations, distance_matrix, cache):
    n = len(locations)
    chunks = [(i, min(i + CHUNK_SIZE, n)) for i in range(0, n, CHUNK_SIZE)]

    for orig_s, orig_e in chunks:
        for dest_s, dest_e in chunks:
            ch_orig = locations[orig_s:orig_e]
            ch_dest = locations[dest_s:dest_e]

            missing = []
            for i_rel, i_abs in enumerate(range(orig_s, orig_e)):
                for j_rel, j_abs in enumerate(range(dest_s, dest_e)):
                    key = get_cache_key(locations[i_abs], locations[j_abs])
                    if key and key in cache:
                        try:
                            distance_matrix[i_abs][j_abs] = float(cache[key]['distance_m'])
                        except:
                            missing.append((i_rel, j_rel, i_abs, j_abs))
                    else:
                        missing.append((i_rel, j_rel, i_abs, j_abs))

            if not missing:
                continue

            try:
                result = gmaps.distance_matrix(
                    origins=ch_orig, destinations=ch_dest,
                    mode='driving', units='metric')

                if result['status'] != 'OK':
                    continue

                for i_rel in range(len(ch_orig)):
                    for j_rel in range(len(ch_dest)):
                        i_abs = orig_s + i_rel
                        j_abs = dest_s + j_rel
                        try:
                            el = result['rows'][i_rel]['elements'][j_rel]
                            if el['status'] == 'OK':
                                d = float(el['distance']['value'])
                                distance_matrix[i_abs][j_abs] = max(0.0, d)
                                key = get_cache_key(locations[i_abs], locations[j_abs])
                                if key:
                                    cache[key] = {
                                        'distance_m': d,
                                        'duration_s': float(el['duration']['value']),
                                        'cached_at': datetime.now().isoformat()
                                    }
                            else:
                                distance_matrix[i_abs][j_abs] = 100000.0
                        except:
                            distance_matrix[i_abs][j_abs] = 100000.0

                save_distances_cache(cache)
                time.sleep(0.1)

            except Exception as e:
                print(f"Erreur chunk API: {e}")

    # Completer les cases manquantes
    for i in range(n):
        for j in range(n):
            if i == j:
                distance_matrix[i][j] = 0.0
            elif distance_matrix[i][j] == 0.0:
                distance_matrix[i][j] = _estimate_single_distance(
                    locations[i], locations[j])

    return distance_matrix

def _estimate_single_distance(origin, destination):
    try:
        op = str(origin).split(',')
        dp = str(destination).split(',')
        if len(op) >= 2 and len(dp) >= 2:
            lat1, lon1 = float(op[0].strip()), float(op[1].strip())
            lat2, lon2 = float(dp[0].strip()), float(dp[1].strip())
            R = 6371000
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = (math.sin(dlat/2)**2 +
                 math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
                 math.sin(dlon/2)**2)
            return max(0.0, R * 2 * math.asin(math.sqrt(a)) * 1.3)
    except:
        pass
    return 100000.0

def _estimate_distance_matrix(locations):
    n = len(locations)
    dm = [[0.0] * n for _ in range(n)]
    coords = []
    for loc in locations:
        try:
            p = str(loc).split(',')
            coords.append((float(p[0].strip()), float(p[1].strip())) if len(p) >= 2 else None)
        except:
            coords.append(None)

    for i in range(n):
        for j in range(n):
            if i != j:
                if coords[i] and coords[j]:
                    lat1, lon1 = coords[i]
                    lat2, lon2 = coords[j]
                    R = 6371000
                    dlat = math.radians(lat2 - lat1)
                    dlon = math.radians(lon2 - lon1)
                    a = (math.sin(dlat/2)**2 +
                         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
                         math.sin(dlon/2)**2)
                    dm[i][j] = max(0.0, R * 2 * math.asin(math.sqrt(a)) * 1.3)
                else:
                    dm[i][j] = 100000.0
    return dm

# ==================== DEMARRAGE ====================

if __name__ == '__main__':
    print("Demarrage API sur http://localhost:5000")
    print("Test: http://localhost:5000/health")
    if gmaps is None:
        print("Google Maps non configure - distances estimees")
    app.run(host='0.0.0.0', port=5000, debug=True)
