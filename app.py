from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import googlemaps
import os

app = Flask(__name__)

# Configuration Google Maps
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', 'AIzaSyAI-VXfNrlF7RmK9ED7Eo6_FMfxYWyE-nU')
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY) if GOOGLE_MAPS_API_KEY != 'VOTRE_CLE_API_ICI' else None

# ==================== VALIDATION ET FILTRAGE ====================

def valider_collecte(c):
    """Vérifie qu'une collecte a les données minimales requises"""
    if not c.get('adresse') or c['adresse'].strip() == '':
        return False
    if not c.get('client') or c['client'].strip() == '':
        return False
    return True

def valider_livraison(l):
    """Vérifie qu'une livraison a les données minimales requises"""
    if not l.get('adresse') or l['adresse'].strip() == '':
        return False
    if not l.get('client') or l['client'].strip() == '':
        return False
    return True

def valider_transit(t):
    """Vérifie qu'un transit a les données minimales requises"""
    if not t.get('adresse_depart') or t['adresse_depart'].strip() == '':
        return False
    if not t.get('adresse_arrivee') or t['adresse_arrivee'].strip() == '':
        return False
    if not t.get('matiere_transit') or t['matiere_transit'].strip() == '':
        return False
    return True

def valider_transporteur(t):
    """Vérifie qu'un transporteur a les données minimales requises"""
    if not t.get('adresse') or t['adresse'].strip() == '':
        return False
    if not t.get('client') or t['client'].strip() == '':
        return False
    if not t.get('ID_transporteur') or t['ID_transporteur'].strip() == '':
        return False
    return True

def filtrer_donnees(collectes, livraisons, transits, transporteurs):
    """Filtre toutes les entrées vides ou invalides"""
    collectes_valides = [c for c in collectes if valider_collecte(c)]
    livraisons_valides = [l for l in livraisons if valider_livraison(l)]
    transits_valides = [t for t in transits if valider_transit(t)]
    transporteurs_valides = [t for t in transporteurs if valider_transporteur(t)]
    
    print(f"\n🔍 Filtrage des données:")
    print(f"   Collectes: {len(collectes)} → {len(collectes_valides)} valides")
    print(f"   Livraisons: {len(livraisons)} → {len(livraisons_valides)} valides")
    print(f"   Transits: {len(transits)} → {len(transits_valides)} valides")
    print(f"   Transporteurs: {len(transporteurs)} → {len(transporteurs_valides)} valides")
    
    return collectes_valides, livraisons_valides, transits_valides, transporteurs_valides

# ==================== ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Test simple pour vérifier que l'API fonctionne"""
    return jsonify({
        "status": "OK",
        "message": "API OR-Tools opérationnelle !",
        "google_maps_configured": gmaps is not None
    })

@app.route('/optimize', methods=['POST'])
def optimize_route():
    """Point d'entrée principal"""
    try:
        data = request.json
        print("📥 Données reçues:", data)
        
        collectes = data.get('collectes', [])
        livraisons = data.get('livraisons', [])
        transits = data.get('Transits', [])
        transporteurs = data.get('Transporteurs', [])
        site = data.get('site_traitement', {})
        contraintes = data.get('contraintes', {})
        
        # Filtrer les données vides
        collectes, livraisons, transits, transporteurs = filtrer_donnees(
            collectes, livraisons, transits, transporteurs
        )
        
        if not transporteurs:
            return jsonify({
                "error": "Aucun transporteur valide",
                "details": "Veuillez fournir au moins un transporteur avec des données complètes"
            }), 400
        
        if not collectes and not livraisons and not transits:
            return jsonify({
                "error": "Aucun trajet valide",
                "details": "Veuillez fournir au moins un trajet avec des données complètes"
            }), 400
        
        # Optimisation
        solution = optimize_with_transporteurs(collectes, livraisons, transits, transporteurs, site, contraintes)
        
        print("✅ Solution calculée")
        return jsonify(solution)
    
    except Exception as e:
        print("❌ Erreur:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 400

# ==================== OPTIMISATION PRINCIPALE ====================

def optimize_with_transporteurs(collectes, livraisons, transits, transporteurs, site, contraintes):
    """
    Optimise en testant chaque transporteur
    Tient compte des collectes avec transporteur imposé
    """
    
    print(f"\n🚚 Test de {len(transporteurs)} transporteur(s)")
    
    solutions_par_transporteur = []
    
    for transporteur in transporteurs:
        print(f"\n{'='*60}")
        print(f"🚚 Test du transporteur: {transporteur['client']} (ID: {transporteur['ID_transporteur']})")
        print(f"{'='*60}")
        
        # Filtrer les collectes selon le transporteur
        collectes_pour_ce_transporteur = []
        collectes_incompatibles = []
        
        for c in collectes:
            transporteur_impose = c.get('transporteur', '').strip()
            
            if transporteur_impose == '':
                # Pas de transporteur imposé, libre
                collectes_pour_ce_transporteur.append(c)
            elif transporteur_impose == transporteur['ID_transporteur']:
                # Transporteur imposé correspond
                collectes_pour_ce_transporteur.append(c)
            else:
                # Transporteur imposé ne correspond pas
                collectes_incompatibles.append(c)
                print(f"   ❌ Collecte {c.get('ID_entree', 'N/A')} incompatible (impose transporteur {transporteur_impose})")
        
        solution = calculate_route_with_transporteur(
            collectes_pour_ce_transporteur, livraisons, transits,
            transporteur, site, contraintes
        )
        
        if solution.get('success'):
            # Ajouter les collectes incompatibles aux trajets non inclus
            if collectes_incompatibles:
                if 'trajets_non_inclus' not in solution:
                    solution['trajets_non_inclus'] = []
                
                for c in collectes_incompatibles:
                    solution['trajets_non_inclus'].append({
                        'type': 'collecte',
                        'ID_entree': c.get('ID_entree', ''),
                        'client': c.get('client', ''),
                        'raison': f"Transporteur incompatible (impose {c.get('transporteur', '')})"
                    })
                
                # Recalculer le taux de complétion
                nb_total = len(collectes) + len(livraisons) + len(transits)
                nb_inclus = nb_total - len(solution['trajets_non_inclus'])
                solution['statistiques']['nombre_collectes_totales'] = len(collectes)
                solution['statistiques']['taux_completion'] = f"{(nb_inclus / nb_total * 100):.0f}%" if nb_total > 0 else "0%"
                solution['avertissement'] = f"{len(solution['trajets_non_inclus'])} trajet(s) non inclus"
            
            solutions_par_transporteur.append({
                'transporteur': transporteur,
                'solution': solution
            })
    
    if not solutions_par_transporteur:
        return {
            "error": "Aucune solution trouvée",
            "details": "Aucun transporteur ne permet de satisfaire les contraintes"
        }
    
    # Choisir le meilleur transporteur
    meilleure = max(
        solutions_par_transporteur,
        key=lambda x: (
            x['solution']['statistiques']['nombre_collectes_incluses'] +
            x['solution']['statistiques']['nombre_livraisons_incluses'] +
            x['solution']['statistiques']['nombre_transits_inclus'],
            -x['solution']['statistiques']['distance_totale_km'],
            -x['solution']['statistiques']['duree_totale_heures']
        )
    )
    
    print(f"\n{'='*60}")
    print(f"🏆 MEILLEUR TRANSPORTEUR: {meilleure['transporteur']['client']}")
    print(f"{'='*60}")
    
    result = meilleure['solution']
    result['transporteur_optimal'] = {
        'ID_transporteur': meilleure['transporteur']['ID_transporteur'],
        'nom': meilleure['transporteur']['client'],
        'adresse': meilleure['transporteur']['adresse']
    }
    
    # Comparaison avec autres transporteurs
    if len(solutions_par_transporteur) > 1:
        comparaisons = []
        for sol in solutions_par_transporteur:
            if sol['transporteur']['ID_transporteur'] != meilleure['transporteur']['ID_transporteur']:
                comparaisons.append({
                    'ID_transporteur': sol['transporteur']['ID_transporteur'],
                    'nom': sol['transporteur']['client'],
                    'distance_km': sol['solution']['statistiques']['distance_totale_km'],
                    'duree_heures': sol['solution']['statistiques']['duree_totale_heures'],
                    'trajets_couverts': (
                        sol['solution']['statistiques']['nombre_collectes_incluses'] +
                        sol['solution']['statistiques']['nombre_livraisons_incluses'] +
                        sol['solution']['statistiques']['nombre_transits_inclus']
                    )
                })
        
        result['transporteurs_alternatifs'] = comparaisons
        
        meilleure_distance = result['statistiques']['distance_totale_km']
        if comparaisons:
            autre_distance = comparaisons[0]['distance_km']
            economie = autre_distance - meilleure_distance
            result['transporteur_optimal']['raison'] = (
                f"Économie de {economie:.1f} km par rapport aux alternatives"
            )
    
    return result

# ==================== CALCUL DE ROUTE ====================

def calculate_route_with_transporteur(collectes, livraisons, transits, transporteur, site, contraintes):
    """
    Calcule la tournée optimale pour UN transporteur donné
    """
    
    locations = []
    location_info = []
    
    # Transporteur (index 0)
    locations.append(transporteur['adresse'])
    location_info.append({
        'type': 'transporteur',
        'nom': transporteur['client'],
        'adresse': transporteur['adresse'],
        'ID_transporteur': transporteur['ID_transporteur']
    })
    
    # Site de traitement (index 1)
    locations.append(site['adresse'])
    location_info.append({
        'type': 'site',
        'nom': site.get('nom', 'Site'),
        'adresse': site['adresse']
    })
    
    # Collectes
    collecte_indices = []
    for c in collectes:
        locations.append(c['adresse'])
        collecte_indices.append(len(locations) - 1)
        location_info.append({
            'type': 'collecte',
            'nom': c['client'],
            'adresse': c['adresse'],
            'ID_entree': c.get('ID_entree', ''),
            'date_fixe': c.get('date_fixe', ''),
            'date_flexible_debut': c.get('date_flexible_debut', ''),
            'date_flexible_fin': c.get('date_flexible_fin', ''),
            'transporteur': c.get('transporteur', '')
        })
    
    # Livraisons
    livraison_indices = []
    for l in livraisons:
        locations.append(l['adresse'])
        livraison_indices.append(len(locations) - 1)
        location_info.append({
            'type': 'livraison',
            'nom': l['client'],
            'adresse': l['adresse'],
            'ID_sortie': l.get('ID_sortie', ''),
            'date_fixe': l.get('date_fixe', ''),
            'date_flexible_debut': l.get('date_flexible_debut', ''),
            'date_flexible_fin': l.get('date_flexible_fin', '')
        })
    
    # Transits
    transit_indices = []
    for idx, t in enumerate(transits):
        # Point de départ
        locations.append(t['adresse_depart'])
        depart_idx = len(locations) - 1
        location_info.append({
            'type': 'transit_depart',
            'nom': f"Transit - Chargement ({t.get('matiere_transit', '')})",
            'adresse': t['adresse_depart'],
            'ID_transit': t.get('ID_transit', ''),
            'matiere': t.get('matiere_transit', ''),
            'date_fixe': t.get('date_fixe', ''),
            'date_flexible_debut': t.get('date_flexible_debut', ''),
            'date_flexible_fin': t.get('date_flexible_fin', ''),
            'transit_id': idx
        })
        
        # Point d'arrivée
        locations.append(t['adresse_arrivee'])
        arrivee_idx = len(locations) - 1
        location_info.append({
            'type': 'transit_arrivee',
            'nom': f"Transit - Livraison ({t.get('matiere_transit', '')})",
            'adresse': t['adresse_arrivee'],
            'ID_transit': t.get('ID_transit', ''),
            'matiere': t.get('matiere_transit', ''),
            'date_fixe': t.get('date_fixe', ''),
            'date_flexible_debut': t.get('date_flexible_debut', ''),
            'date_flexible_fin': t.get('date_flexible_fin', ''),
            'transit_id': idx
        })
        
        transit_indices.append((depart_idx, arrivee_idx))
    
    print(f"📍 {len(locations)} lieux à optimiser")
    print(f"   - Transporteur: index 0 ({transporteur['client']})")
    print(f"   - Site: index 1")
    print(f"   - Collectes: {len(collecte_indices)}")
    print(f"   - Livraisons: {len(livraison_indices)}")
    print(f"   - Transits: {len(transit_indices)}")
    
    # Extraire contraintes
    duree_max = None
    vitesse_moyenne = 70
    temps_operation_minutes = 30
    
    if contraintes:
        if 'duree_max_en_heure' in contraintes:
            try:
                duree_max = float(contraintes['duree_max_en_heure'])
                print(f"⏱️  Contrainte de durée: {duree_max}h maximum")
            except:
                print("⚠️  Durée max invalide, ignorée")
        
        if 'vitesse_moyenne_kmh' in contraintes:
            try:
                vitesse_moyenne = float(contraintes['vitesse_moyenne_kmh'])
                print(f"🚗 Vitesse moyenne: {vitesse_moyenne} km/h")
            except:
                print("⚠️  Vitesse moyenne invalide, valeur par défaut 70 km/h utilisée")
        
        if 'temps_operation_minutes' in contraintes:
            try:
                temps_operation_minutes = float(contraintes['temps_operation_minutes'])
                print(f"⏳ Temps opération: {temps_operation_minutes} minutes")
            except:
                print("⚠️  Temps opération invalide, valeur par défaut 30 min utilisée")
    
    params_calcul = {
        'vitesse_moyenne_kmh': vitesse_moyenne,
        'temps_operation_heures': temps_operation_minutes / 60
    }
    
    print(f"\n📊 Paramètres de calcul:")
    print(f"   - Vitesse moyenne: {vitesse_moyenne} km/h")
    print(f"   - Temps opération: {temps_operation_minutes} min ({temps_operation_minutes/60:.2f}h)")
    print(f"   - Durée max: {duree_max}h" if duree_max else "   - Durée max: Pas de limite")
    
    # Calculer distances
    print("🗺️  Calcul des distances...")
    distance_matrix = get_distance_matrix(locations)
    
    # Créer segments
    print("\n📦 Création des segments possibles:")
    segments = creer_segments_possibles(
        collecte_indices, livraison_indices, transit_indices,
        location_info, distance_matrix, params_calcul
    )
    print(f"\n🔍 {len(segments)} segments générés")
    
    # Trouver meilleure solution
    best_solution = find_best_solution_with_dates(
        segments, collecte_indices, livraison_indices, transit_indices,
        location_info, distance_matrix, duree_max
    )
    
    return best_solution

# ==================== CRÉATION DES SEGMENTS ====================

def creer_segments_possibles(collecte_indices, livraison_indices, transit_indices, location_info, distance_matrix, params_calcul):
    """
    Crée tous les segments de trajet possibles.
    
    Règle fondamentale : après un transit le camion est VIDE.
    Il n'y a donc jamais de retour au site après un transit,
    car le site n'est nécessaire que pour décharger une collecte.
    
    Segments avec transit après livraison :
      - Livraison → Transit → Collecte → Site  (enchaîne une collecte après)
      - Livraison → Transit → Transporteur     (fin de tournée directe)
    """
    VITESSE_MOYENNE_KMH = params_calcul['vitesse_moyenne_kmh']
    TEMPS_OPERATION_HEURES = params_calcul['temps_operation_heures']
    
    segments = []
    
    # --- SEGMENTS DE DÉBUT ---
    
    # Transporteur → Collecte → Site
    for col_idx in collecte_indices:
        segment = {
            'type': 'debut_collecte',
            'arrets': [0, col_idx, 1],
            'distance': distance_matrix[0][col_idx] + distance_matrix[col_idx][1],
            'info_collecte': location_info[col_idx]
        }
        segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + TEMPS_OPERATION_HEURES
        segments.append(segment)
    
    # Transporteur → Site
    segment = {
        'type': 'debut_site',
        'arrets': [0, 1],
        'distance': distance_matrix[0][1],
        'info': None
    }
    segment['duree_heures'] = segment['distance'] / 1000 / VITESSE_MOYENNE_KMH
    segments.append(segment)
    
    # Transporteur → Transit → (arrivée du transit, camion vide)
    for depart_idx, arrivee_idx in transit_indices:
        segment = {
            'type': 'debut_transit',
            'arrets': [0, depart_idx, arrivee_idx],
            'distance': distance_matrix[0][depart_idx] + distance_matrix[depart_idx][arrivee_idx],
            'info_transit': location_info[depart_idx]
        }
        segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (2 * TEMPS_OPERATION_HEURES)
        segments.append(segment)
        
        # Transporteur → Transit → Collecte → Site
        for col_idx in collecte_indices:
            segment = {
                'type': 'debut_transit_collecte',
                'arrets': [0, depart_idx, arrivee_idx, col_idx, 1],
                'distance': (distance_matrix[0][depart_idx] +
                           distance_matrix[depart_idx][arrivee_idx] +
                           distance_matrix[arrivee_idx][col_idx] +
                           distance_matrix[col_idx][1]),
                'info_transit': location_info[depart_idx],
                'info_collecte': location_info[col_idx]
            }
            segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (3 * TEMPS_OPERATION_HEURES)
            segments.append(segment)
    
    # --- SEGMENTS DU MILIEU (depuis le site) ---
    
    # Site → Collecte → Site
    for col_idx in collecte_indices:
        segment = {
            'type': 'collecte_simple',
            'arrets': [1, col_idx, 1],
            'distance': distance_matrix[1][col_idx] + distance_matrix[col_idx][1],
            'info_collecte': location_info[col_idx]
        }
        segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + TEMPS_OPERATION_HEURES
        segments.append(segment)
    
    # Site → Livraison → Site
    for liv_idx in livraison_indices:
        segment = {
            'type': 'livraison_simple',
            'arrets': [1, liv_idx, 1],
            'distance': distance_matrix[1][liv_idx] + distance_matrix[liv_idx][1],
            'info_livraison': location_info[liv_idx]
        }
        segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + TEMPS_OPERATION_HEURES
        segments.append(segment)
    
    # Site → Livraison → Collecte → Site
    for liv_idx in livraison_indices:
        for col_idx in collecte_indices:
            segment = {
                'type': 'livraison_collecte',
                'arrets': [1, liv_idx, col_idx, 1],
                'distance': (distance_matrix[1][liv_idx] +
                           distance_matrix[liv_idx][col_idx] +
                           distance_matrix[col_idx][1]),
                'info_livraison': location_info[liv_idx],
                'info_collecte': location_info[col_idx]
            }
            segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (2 * TEMPS_OPERATION_HEURES)
            segments.append(segment)
    
    # Site → Transit → Site  ← SUPPRIMÉ (après transit le camion est vide, rien à décharger au site)
    # Ce segment n'existe plus. À la place on a :
    
    # Site → Transit → Collecte → Site (le camion enchaîne une collecte après le transit)
    for depart_idx, arrivee_idx in transit_indices:
        for col_idx in collecte_indices:
            segment = {
                'type': 'site_transit_collecte',
                'arrets': [1, depart_idx, arrivee_idx, col_idx, 1],
                'distance': (distance_matrix[1][depart_idx] +
                           distance_matrix[depart_idx][arrivee_idx] +
                           distance_matrix[arrivee_idx][col_idx] +
                           distance_matrix[col_idx][1]),
                'info_transit': location_info[depart_idx],
                'info_collecte': location_info[col_idx]
            }
            segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (3 * TEMPS_OPERATION_HEURES)
            segments.append(segment)
    
    # Site → Transit → Transporteur (fin de tournée après transit)
    for depart_idx, arrivee_idx in transit_indices:
        segment = {
            'type': 'site_transit_fin',
            'arrets': [1, depart_idx, arrivee_idx, 0],
            'distance': (distance_matrix[1][depart_idx] +
                       distance_matrix[depart_idx][arrivee_idx] +
                       distance_matrix[arrivee_idx][0]),
            'info_transit': location_info[depart_idx]
        }
        segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (2 * TEMPS_OPERATION_HEURES)
        segments.append(segment)
    
    # Site → Livraison → Transit → Collecte → Site
    for liv_idx in livraison_indices:
        for depart_idx, arrivee_idx in transit_indices:
            for col_idx in collecte_indices:
                segment = {
                    'type': 'livraison_transit_collecte',
                    'arrets': [1, liv_idx, depart_idx, arrivee_idx, col_idx, 1],
                    'distance': (distance_matrix[1][liv_idx] +
                               distance_matrix[liv_idx][depart_idx] +
                               distance_matrix[depart_idx][arrivee_idx] +
                               distance_matrix[arrivee_idx][col_idx] +
                               distance_matrix[col_idx][1]),
                    'info_livraison': location_info[liv_idx],
                    'info_transit': location_info[depart_idx],
                    'info_collecte': location_info[col_idx]
                }
                segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (4 * TEMPS_OPERATION_HEURES)
                segments.append(segment)
    
    # Site → Livraison → Transit → Transporteur (fin directe)
    for liv_idx in livraison_indices:
        for depart_idx, arrivee_idx in transit_indices:
            segment = {
                'type': 'livraison_transit_fin',
                'arrets': [1, liv_idx, depart_idx, arrivee_idx, 0],
                'distance': (distance_matrix[1][liv_idx] +
                           distance_matrix[liv_idx][depart_idx] +
                           distance_matrix[depart_idx][arrivee_idx] +
                           distance_matrix[arrivee_idx][0]),
                'info_livraison': location_info[liv_idx],
                'info_transit': location_info[depart_idx]
            }
            segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (3 * TEMPS_OPERATION_HEURES)
            segments.append(segment)
    
    # Transit → Transit (enchaînement depuis le site)
    # Après le 2ème transit le camion est vide → pas de retour au site.
    # À la place : site → transit1 → transit2 → collecte → site
    for depart_idx1, arrivee_idx1 in transit_indices:
        for depart_idx2, arrivee_idx2 in transit_indices:
            if location_info[depart_idx1]['transit_id'] != location_info[depart_idx2]['transit_id']:
                # Site → Transit1 → Transit2 → Collecte → Site
                for col_idx in collecte_indices:
                    segment = {
                        'type': 'transit_transit_collecte',
                        'arrets': [1, depart_idx1, arrivee_idx1, depart_idx2, arrivee_idx2, col_idx, 1],
                        'distance': (distance_matrix[1][depart_idx1] +
                                   distance_matrix[depart_idx1][arrivee_idx1] +
                                   distance_matrix[arrivee_idx1][depart_idx2] +
                                   distance_matrix[depart_idx2][arrivee_idx2] +
                                   distance_matrix[arrivee_idx2][col_idx] +
                                   distance_matrix[col_idx][1]),
                        'info_transit1': location_info[depart_idx1],
                        'info_transit2': location_info[depart_idx2],
                        'info_collecte': location_info[col_idx]
                    }
                    segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (5 * TEMPS_OPERATION_HEURES)
                    segments.append(segment)
                
                # Site → Transit1 → Transit2 → Transporteur (fin)
                segment = {
                    'type': 'transit_transit_fin',
                    'arrets': [1, depart_idx1, arrivee_idx1, depart_idx2, arrivee_idx2, 0],
                    'distance': (distance_matrix[1][depart_idx1] +
                               distance_matrix[depart_idx1][arrivee_idx1] +
                               distance_matrix[arrivee_idx1][depart_idx2] +
                               distance_matrix[depart_idx2][arrivee_idx2] +
                               distance_matrix[arrivee_idx2][0]),
                    'info_transit1': location_info[depart_idx1],
                    'info_transit2': location_info[depart_idx2]
                }
                segment['duree_heures'] = (segment['distance'] / 1000 / VITESSE_MOYENNE_KMH) + (4 * TEMPS_OPERATION_HEURES)
                segments.append(segment)
    
    # --- SEGMENTS DE FIN ---
    
    # Site → Transporteur
    segment = {
        'type': 'fin_depuis_site',
        'arrets': [1, 0],
        'distance': distance_matrix[1][0],
        'info': None
    }
    segment['duree_heures'] = segment['distance'] / 1000 / VITESSE_MOYENNE_KMH
    segments.append(segment)
    
    # Livraison → Transporteur
    for liv_idx in livraison_indices:
        segment = {
            'type': 'fin_depuis_livraison',
            'arrets': [liv_idx, 0],
            'distance': distance_matrix[liv_idx][0],
            'info_livraison': location_info[liv_idx]
        }
        segment['duree_heures'] = segment['distance'] / 1000 / VITESSE_MOYENNE_KMH
        segments.append(segment)
    
    # Transit → Transporteur
    for depart_idx, arrivee_idx in transit_indices:
        segment = {
            'type': 'fin_depuis_transit',
            'arrets': [arrivee_idx, 0],
            'distance': distance_matrix[arrivee_idx][0],
            'info_transit': location_info[depart_idx]
        }
        segment['duree_heures'] = segment['distance'] / 1000 / VITESSE_MOYENNE_KMH
        segments.append(segment)
    
    return segments

# ==================== RECHERCHE DE LA MEILLEURE SOLUTION ====================

def find_best_solution_with_dates(segments, collecte_indices, livraison_indices, transit_indices,
                                  location_info, distance_matrix, duree_max_heures):
    """
    Trouve la meilleure date et la meilleure séquence de segments
    """
    
    # Identifier toutes les dates possibles
    print("\n📅 Identification des dates possibles:")
    dates_possibles = set()
    
    for idx in collecte_indices + livraison_indices:
        info = location_info[idx]
        ajouter_dates(info, dates_possibles)
    
    for depart_idx, arrivee_idx in transit_indices:
        info = location_info[depart_idx]
        ajouter_dates(info, dates_possibles)
    
    if not dates_possibles:
        return {
            "error": "Aucune date possible",
            "details": "Aucune contrainte de date définie"
        }
    
    dates_possibles = sorted(list(dates_possibles))
    print(f"\n🔍 {len(dates_possibles)} dates candidates à tester")
    
    # Tester chaque date
    print("\n🎯 Test de chaque date:")
    meilleures_solutions = []
    
    for date_candidate in dates_possibles:
        print(f"\n   📅 Test: {date_candidate.strftime('%d/%m/%Y')}")
        
        segments_compatibles = filtrer_segments_par_date(
            segments, date_candidate, location_info,
            collecte_indices, livraison_indices, transit_indices
        )
        
        if not segments_compatibles:
            print(f"      ❌ Aucun segment compatible")
            continue
        
        print(f"      ✅ {len(segments_compatibles)} segments compatibles")
        
        solution = construire_meilleure_sequence(
            segments_compatibles, collecte_indices, livraison_indices, transit_indices,
            location_info, duree_max_heures, date_candidate
        )
        
        if solution:
            meilleures_solutions.append(solution)
    
    if not meilleures_solutions:
        return {
            "error": "Aucune solution trouvée",
            "details": "Aucune date ne permet de satisfaire les contraintes"
        }
    
    # Choisir la meilleure date
    solution_optimale = max(
        meilleures_solutions,
        key=lambda x: (x['nb_trajets_couverts'], -x['duree_totale'], -x['distance_totale'])
    )
    
    return formater_solution_finale(solution_optimale, location_info,
                                    collecte_indices, livraison_indices, transit_indices)

def ajouter_dates(info, dates_possibles):
    """Ajoute les dates possibles depuis une info de lieu"""
    date_fixe = info.get('date_fixe', '')
    if date_fixe and date_fixe.strip() != '':
        try:
            d = datetime.strptime(date_fixe.strip(), '%Y-%m-%d')
            dates_possibles.add(d)
            print(f"   📌 {info['nom']}: Date fixe {d.strftime('%d/%m/%Y')}")
        except:
            pass
    
    date_debut = info.get('date_flexible_debut', '')
    date_fin = info.get('date_flexible_fin', '')
    if date_debut and date_fin and date_debut.strip() != '' and date_fin.strip() != '':
        try:
            d_debut = datetime.strptime(date_debut.strip(), '%Y-%m-%d')
            d_fin = datetime.strptime(date_fin.strip(), '%Y-%m-%d')
            current = d_debut
            while current <= d_fin:
                dates_possibles.add(current)
                current += timedelta(days=1)
            print(f"   📅 {info['nom']}: Flexible {d_debut.strftime('%d/%m/%Y')} - {d_fin.strftime('%d/%m/%Y')}")
        except:
            pass

def filtrer_segments_par_date(segments, date_candidate, location_info,
                              collecte_indices, livraison_indices, transit_indices):
    """Filtre les segments compatibles avec une date donnée"""
    segments_compatibles = []
    
    for segment in segments:
        compatible = True
        
        for arret_idx in segment['arrets']:
            if arret_idx in [0, 1]:
                continue
            
            info = location_info[arret_idx]
            
            date_fixe = info.get('date_fixe', '')
            if date_fixe and date_fixe.strip() != '':
                try:
                    d = datetime.strptime(date_fixe.strip(), '%Y-%m-%d')
                    if d != date_candidate:
                        compatible = False
                        break
                except:
                    pass
            
            date_debut = info.get('date_flexible_debut', '')
            date_fin = info.get('date_flexible_fin', '')
            if date_debut and date_fin and date_debut.strip() != '' and date_fin.strip() != '':
                try:
                    d_debut = datetime.strptime(date_debut.strip(), '%Y-%m-%d')
                    d_fin = datetime.strptime(date_fin.strip(), '%Y-%m-%d')
                    if not (d_debut <= date_candidate <= d_fin):
                        compatible = False
                        break
                except:
                    pass
        
        if compatible:
            segments_compatibles.append(segment)
    
    return segments_compatibles

# ==================== CONSTRUCTION DE LA SÉQUENCE ====================

def construire_meilleure_sequence(segments, collecte_indices, livraison_indices, transit_indices,
                                  location_info, duree_max_heures, date_candidate):
    """
    Construit la meilleure séquence de segments pour une date donnée.
    
    Après un transit le camion est vide : les segments qui finissent
    au transporteur (index 0) sont des fins de tournée valides.
    """
    
    collectes_restantes = set(collecte_indices)
    livraisons_restantes = set(livraison_indices)
    transits_restants = set(range(len(transit_indices)))
    
    sequence = []
    duree_totale = 0
    distance_totale = 0
    position_actuelle = 0
    
    # 1. DÉBUT
    segments_debut = [s for s in segments if s['type'] in [
        'debut_collecte', 'debut_site', 'debut_transit', 'debut_transit_collecte'
    ]]
    
    print(f"\n🔍 DEBUG DÉBUT: {len(segments_debut)} segments de début trouvés")
    for seg in segments_debut:
        print(f"   - {seg['type']}: arrets={seg['arrets']}, durée={seg['duree_heures']:.2f}h")
    
    # Privilégier les segments utiles (debut_site en dernier)
    segments_debut_tries = sorted(segments_debut, key=lambda x: (
        0 if x['type'] == 'debut_site' else -1,
        x['duree_heures']
    ))
    
    print(f"\n🔍 DEBUG TRI: Ordre après tri:")
    for i, seg in enumerate(segments_debut_tries):
        print(f"   {i+1}. {seg['type']}: priorité={0 if seg['type'] == 'debut_site' else -1}, durée={seg['duree_heures']:.2f}h")
    
    segment_choisi = None
    for seg in segments_debut_tries:
        print(f"\n🔍 DEBUG TEST: {seg['type']} (durée={seg['duree_heures']:.2f}h, max={duree_max_heures})")
        if duree_max_heures is None or seg['duree_heures'] <= duree_max_heures:
            valide = True
            if seg['type'] == 'debut_collecte':
                if seg['arrets'][1] not in collectes_restantes:
                    valide = False
                    print(f"   ❌ Collecte non disponible")
            elif seg['type'] == 'debut_transit':
                transit_id = location_info[seg['arrets'][1]]['transit_id']
                print(f"   → transit_id={transit_id}, transits_restants={transits_restants}")
                if transit_id not in transits_restants:
                    valide = False
                    print(f"   ❌ Transit non disponible")
            elif seg['type'] == 'debut_transit_collecte':
                transit_id = location_info[seg['arrets'][1]]['transit_id']
                if transit_id not in transits_restants or seg['arrets'][3] not in collectes_restantes:
                    valide = False
                    print(f"   ❌ Transit ou collecte non disponible")
            elif seg['type'] == 'debut_site':
                # debut_site n'est valide que s'il reste des trajets à faire depuis le site
                if not (collectes_restantes or livraisons_restantes or transits_restants):
                    valide = False
                    print(f"   ❌ Aucun trajet restant")
            
            print(f"   → valide={valide}")
            if valide:
                segment_choisi = seg
                print(f"   ✅ CHOISI: {seg['type']}")
                break
        else:
            print(f"   ❌ Dépasse durée max")
    
    if not segment_choisi:
        return None
    
    sequence.append(segment_choisi)
    duree_totale += segment_choisi['duree_heures']
    distance_totale += segment_choisi['distance']
    
    # Marquer trajets utilisés du segment de début
    if segment_choisi['type'] == 'debut_collecte':
        collectes_restantes.discard(segment_choisi['arrets'][1])
        position_actuelle = 1
    elif segment_choisi['type'] == 'debut_site':
        position_actuelle = 1
    elif segment_choisi['type'] == 'debut_transit':
        transit_id = location_info[segment_choisi['arrets'][1]]['transit_id']
        transits_restants.discard(transit_id)
        position_actuelle = segment_choisi['arrets'][-1]
    elif segment_choisi['type'] == 'debut_transit_collecte':
        transit_id = location_info[segment_choisi['arrets'][1]]['transit_id']
        transits_restants.discard(transit_id)
        collectes_restantes.discard(segment_choisi['arrets'][3])
        position_actuelle = 1
    
    # 2. MILIEU
    max_iterations = 20
    iterations = 0
    
    while (collectes_restantes or livraisons_restantes or transits_restants) and iterations < max_iterations:
        iterations += 1
        segments_possibles = []
        
        if position_actuelle == 1:  # Au site
            for seg in segments:
                ajouter = False
                
                if seg['type'] == 'collecte_simple' and seg['arrets'][1] in collectes_restantes:
                    ajouter = True
                elif seg['type'] == 'livraison_simple' and seg['arrets'][1] in livraisons_restantes:
                    ajouter = True
                elif seg['type'] == 'livraison_collecte':
                    if seg['arrets'][1] in livraisons_restantes and seg['arrets'][2] in collectes_restantes:
                        ajouter = True
                elif seg['type'] == 'site_transit_collecte':
                    transit_id = location_info[seg['arrets'][1]]['transit_id']
                    if transit_id in transits_restants and seg['arrets'][3] in collectes_restantes:
                        ajouter = True
                elif seg['type'] == 'site_transit_fin':
                    transit_id = location_info[seg['arrets'][1]]['transit_id']
                    if transit_id in transits_restants:
                        ajouter = True
                elif seg['type'] == 'livraison_transit_collecte':
                    transit_id = location_info[seg['arrets'][2]]['transit_id']
                    if (seg['arrets'][1] in livraisons_restantes and
                        transit_id in transits_restants and
                        seg['arrets'][4] in collectes_restantes):
                        ajouter = True
                elif seg['type'] == 'livraison_transit_fin':
                    transit_id = location_info[seg['arrets'][2]]['transit_id']
                    if seg['arrets'][1] in livraisons_restantes and transit_id in transits_restants:
                        ajouter = True
                elif seg['type'] == 'transit_transit_collecte':
                    tid1 = location_info[seg['arrets'][1]]['transit_id']
                    tid2 = location_info[seg['arrets'][3]]['transit_id']
                    if tid1 in transits_restants and tid2 in transits_restants and seg['arrets'][5] in collectes_restantes:
                        ajouter = True
                elif seg['type'] == 'transit_transit_fin':
                    tid1 = location_info[seg['arrets'][1]]['transit_id']
                    tid2 = location_info[seg['arrets'][3]]['transit_id']
                    if tid1 in transits_restants and tid2 in transits_restants:
                        ajouter = True
                
                if ajouter:
                    segments_possibles.append(seg)
        
        else:  # Position autre que site (ex: arrivée d'un transit)
            # Chercher des segments qui partent de cette position
            # Typiquement : segments de collecte ou retour au site/transporteur
            for seg in segments:
                # Le segment doit commencer par notre position actuelle
                if len(seg['arrets']) > 0 and seg['arrets'][0] == position_actuelle:
                    ajouter = False
                    
                    # Vérifier que les trajets du segment sont encore disponibles
                    if seg['type'] == 'fin_depuis_transit':
                        ajouter = True
                    elif 'collecte' in seg['type']:
                        # Vérifier si les collectes sont disponibles
                        collectes_seg = [a for a in seg['arrets'] if a in collectes_restantes]
                        if collectes_seg:
                            ajouter = True
                    
                    if ajouter:
                        segments_possibles.append(seg)
        
        # Filtrer par durée
        segments_possibles = [
            s for s in segments_possibles
            if duree_max_heures is None or (duree_totale + s['duree_heures']) <= duree_max_heures
        ]
        
        if not segments_possibles:
            break
        
        # Trier : privilégier les segments avec le plus de trajets, puis par distance.
        # Les segments finissant au transporteur (index 0) sont déprioritisés
        # sauf s'il n'y a plus d'autres trajets à faire après.
        reste_a_faire = len(collectes_restantes) + len(livraisons_restantes) + len(transits_restants)
        segments_possibles.sort(key=lambda x: (
            # Si plus d'un trajet à faire, on préfère ne pas finir au transporteur
            1 if (x['arrets'][-1] == 0 and reste_a_faire > self_count_trajets(x, location_info)) else 0,
            -len([a for a in x['arrets'] if a not in [0, 1]]),
            x['distance']
        ))
        
        seg = segments_possibles[0]
        sequence.append(seg)
        duree_totale += seg['duree_heures']
        distance_totale += seg['distance']
        
        # Marquer trajets utilisés
        for arret_idx in seg['arrets']:
            if arret_idx in collectes_restantes:
                collectes_restantes.discard(arret_idx)
            if arret_idx in livraisons_restantes:
                livraisons_restantes.discard(arret_idx)
            info = location_info[arret_idx]
            if info['type'] == 'transit_depart':
                transits_restants.discard(info['transit_id'])
        
        position_actuelle = seg['arrets'][-1]
        
        # Si le segment se termine au transporteur, fin de tournée
        if position_actuelle == 0:
            break
    
    # 3. FIN
    # Si on est déjà au transporteur (segment _fin), pas besoin d'ajouter un segment de fin
    if position_actuelle == 0:
        nb_trajets_couverts = (
            len(collecte_indices) - len(collectes_restantes) +
            len(livraison_indices) - len(livraisons_restantes) +
            len(transit_indices) - len(transits_restants)
        )
        
        print(f"      📊 {len(sequence)} segments, {nb_trajets_couverts} trajets, {duree_totale:.1f}h, {distance_totale/1000:.1f}km")
        
        return {
            'date': date_candidate,
            'sequence': sequence,
            'nb_trajets_couverts': nb_trajets_couverts,
            'duree_totale': duree_totale,
            'distance_totale': distance_totale,
            'collectes_restantes': collectes_restantes,
            'livraisons_restantes': livraisons_restantes,
            'transits_restants': transits_restants,
            'duree_max_heures': duree_max_heures
        }
    
    # Sinon on cherche un segment de fin depuis la position actuelle
    segments_fin = [s for s in segments if s['type'] in [
        'fin_depuis_site', 'fin_depuis_livraison', 'fin_depuis_transit'
    ]]
    
    segment_fin = None
    
    if position_actuelle == 1:
        for seg in segments_fin:
            if seg['type'] == 'fin_depuis_site':
                if duree_max_heures is None or (duree_totale + seg['duree_heures']) <= duree_max_heures:
                    segment_fin = seg
                    break
    else:
        for seg in segments_fin:
            if seg['arrets'][0] == position_actuelle:
                if duree_max_heures is None or (duree_totale + seg['duree_heures']) <= duree_max_heures:
                    segment_fin = seg
                    break
    
    if segment_fin:
        sequence.append(segment_fin)
        duree_totale += segment_fin['duree_heures']
        distance_totale += segment_fin['distance']
    else:
        return None
    
    nb_trajets_couverts = (
        len(collecte_indices) - len(collectes_restantes) +
        len(livraison_indices) - len(livraisons_restantes) +
        len(transit_indices) - len(transits_restants)
    )
    
    print(f"      📊 {len(sequence)} segments, {nb_trajets_couverts} trajets, {duree_totale:.1f}h, {distance_totale/1000:.1f}km")
    
    return {
        'date': date_candidate,
        'sequence': sequence,
        'nb_trajets_couverts': nb_trajets_couverts,
        'duree_totale': duree_totale,
        'distance_totale': distance_totale,
        'collectes_restantes': collectes_restantes,
        'livraisons_restantes': livraisons_restantes,
        'transits_restants': transits_restants,
        'duree_max_heures': duree_max_heures
    }

def self_count_trajets(segment, location_info):
    """Compte le nombre de trajets utiles dans un segment (hors transporteur et site)"""
    count = 0
    for arret_idx in segment['arrets']:
        if arret_idx not in [0, 1]:
            info = location_info[arret_idx]
            # On compte une fois par trajet : collecte, livraison, transit_depart
            if info['type'] in ['collecte', 'livraison', 'transit_depart']:
                count += 1
    return count

# ==================== FORMATAGE DE LA SOLUTION ====================

def formater_solution_finale(solution, location_info, collecte_indices, livraison_indices, transit_indices):
    """
    Formate la solution finale avec les IDs
    """
    date_optimale = solution['date']
    sequence = solution['sequence']
    date_str = date_optimale.strftime('%Y-%m-%d')
    
    itineraire_brut = []
    phase = 1
    
    for seg_num, segment in enumerate(sequence):
        for i, arret_idx in enumerate(segment['arrets']):
            info = location_info[arret_idx]
            
            # Déterminer le type d'arrêt
            if info['type'] == 'transporteur':
                type_arret = 'depart_transporteur' if (seg_num == 0 and i == 0) else 'retour_transporteur'
            elif info['type'] == 'site':
                est_arrivee = False
                est_depart = False
                
                if i > 0:
                    info_precedent = location_info[segment['arrets'][i-1]]
                    if info_precedent['type'] in ['collecte', 'transit_arrivee']:
                        est_arrivee = True
                
                if i < len(segment['arrets']) - 1:
                    info_suivant = location_info[segment['arrets'][i+1]]
                    if info_suivant['type'] in ['livraison', 'collecte', 'transit_depart']:
                        est_depart = True
                
                if est_arrivee and est_depart:
                    type_arret = 'passage_site'
                elif est_depart:
                    type_arret = 'depart_site'
                elif est_arrivee:
                    type_arret = 'arrivee_site'
                else:
                    type_arret = 'passage_site'
            elif info['type'] == 'collecte':
                type_arret = 'collecte'
            elif info['type'] == 'livraison':
                type_arret = 'livraison'
            elif info['type'] == 'transit_depart':
                type_arret = 'transit_chargement'
            elif info['type'] == 'transit_arrivee':
                type_arret = 'transit_livraison'
            else:
                type_arret = info['type']
            
            # Construire l'arrêt avec les IDs
            arret = {
                'phase': phase,
                'type': type_arret,
                'client': info['nom'],
                'adresse': info['adresse'],
                'date_prevue': date_str,
                'idx': arret_idx
            }
            
            # Ajouter les IDs selon le type
            if info['type'] == 'transporteur':
                arret['ID_transporteur'] = info.get('ID_transporteur', '')
            elif info['type'] == 'collecte':
                arret['ID_entree'] = info.get('ID_entree', '')
            elif info['type'] == 'livraison':
                arret['ID_sortie'] = info.get('ID_sortie', '')
            elif info['type'] in ['transit_depart', 'transit_arrivee']:
                arret['ID_transit'] = info.get('ID_transit', '')
                arret['matiere'] = info.get('matiere', '')
            
            itineraire_brut.append(arret)
        
        phase += 1
    
    # Dédupliquer les passages au site consécutifs
    itineraire = []
    ordre = 1
    i = 0
    
    while i < len(itineraire_brut):
        arret_actuel = itineraire_brut[i]
        
        if arret_actuel['type'] in ['arrivee_site', 'depart_site', 'passage_site']:
            if i + 1 < len(itineraire_brut):
                arret_suivant = itineraire_brut[i + 1]
                if arret_suivant['type'] in ['arrivee_site', 'depart_site', 'passage_site']:
                    itineraire.append({
                        'ordre': ordre,
                        'phase': arret_actuel['phase'],
                        'type': 'passage_site',
                        'client': arret_actuel['client'],
                        'adresse': arret_actuel['adresse'],
                        'date_prevue': arret_actuel['date_prevue']
                    })
                    ordre += 1
                    i += 2
                    continue
        
        arret_final = arret_actuel.copy()
        arret_final['ordre'] = ordre
        del arret_final['idx']
        itineraire.append(arret_final)
        ordre += 1
        i += 1
    
    # Trajets non inclus
    collectes_restantes = solution['collectes_restantes']
    livraisons_restantes = solution['livraisons_restantes']
    transits_restants = solution['transits_restants']
    
    trajets_non_inclus = []
    for idx in collectes_restantes:
        trajets_non_inclus.append({
            'type': 'collecte',
            'ID_entree': location_info[idx].get('ID_entree', ''),
            'client': location_info[idx]['nom'],
            'raison': 'Contrainte de durée maximale dépassée ou date incompatible'
        })
    for idx in livraisons_restantes:
        trajets_non_inclus.append({
            'type': 'livraison',
            'ID_sortie': location_info[idx].get('ID_sortie', ''),
            'client': location_info[idx]['nom'],
            'raison': 'Contrainte de durée maximale dépassée ou date incompatible'
        })
    for transit_id in transits_restants:
        depart_idx, _ = transit_indices[transit_id]
        trajets_non_inclus.append({
            'type': 'transit',
            'ID_transit': location_info[depart_idx].get('ID_transit', ''),
            'client': location_info[depart_idx]['nom'],
            'matiere': location_info[depart_idx].get('matiere', ''),
            'raison': 'Contrainte de durée maximale dépassée ou date incompatible'
        })
    
    nb_total_trajets = len(collecte_indices) + len(livraison_indices) + len(transit_indices)
    nb_trajets_inclus = solution['nb_trajets_couverts']
    
    result = {
        'success': True,
        'solution_complete': len(trajets_non_inclus) == 0,
        'date_optimale': date_str,
        'date_optimale_formatee': date_optimale.strftime('%d/%m/%Y'),
        'itineraire': itineraire,
        'nombre_segments': len(sequence),
        'statistiques': {
            'distance_totale_km': round(solution['distance_totale'] / 1000, 2),
            'duree_totale_heures': round(solution['duree_totale'], 2),
            'duree_max_autorisee_heures': solution.get('duree_max_heures'),
            'cout_estime_euros': round(solution['distance_totale'] / 1000 * 1.5, 2),
            'nombre_collectes_incluses': len(collecte_indices) - len(collectes_restantes),
            'nombre_collectes_totales': len(collecte_indices),
            'nombre_livraisons_incluses': len(livraison_indices) - len(livraisons_restantes),
            'nombre_livraisons_totales': len(livraison_indices),
            'nombre_transits_inclus': len(transit_indices) - len(transits_restants),
            'nombre_transits_totaux': len(transit_indices),
            'taux_completion': f"{(nb_trajets_inclus / nb_total_trajets * 100):.0f}%" if nb_total_trajets > 0 else "0%"
        },
        'explication': {
            'methode': 'Optimisation avec transporteurs, segments intelligents et transits',
            'date_choisie_raison': f"Permet de couvrir {nb_trajets_inclus}/{nb_total_trajets} trajets"
        }
    }
    
    if trajets_non_inclus:
        result['trajets_non_inclus'] = trajets_non_inclus
        result['avertissement'] = f"{len(trajets_non_inclus)} trajet(s) non inclus"
    
    return result

# ==================== CALCUL DES DISTANCES ====================

def get_distance_matrix(locations):
    """
    Calcule la matrice de distances entre tous les lieux
    """
    n = len(locations)
    distance_matrix = [[0 for _ in range(n)] for _ in range(n)]
    
    if gmaps is None:
        print("⚠️  Google Maps non configuré, utilisation de distances estimées")
        for i in range(n):
            for j in range(n):
                if i != j:
                    distance_matrix[i][j] = (abs(i-j) * 50000) + 20000
        return distance_matrix
    
    try:
        for i in range(n):
            result = gmaps.distance_matrix(
                origins=[locations[i]],
                destinations=locations,
                mode='driving',
                units='metric'
            )
            
            for j in range(n):
                if i != j:
                    try:
                        distance = result['rows'][0]['elements'][j]['distance']['value']
                        distance_matrix[i][j] = distance
                        print(f"   Distance {i}→{j}: {distance/1000:.1f} km")
                    except:
                        distance_matrix[i][j] = 999999
                        print(f"   ⚠️ Pas de route entre {i} et {j}")
        
        return distance_matrix
    
    except Exception as e:
        print(f"❌ Erreur Google Maps: {e}")
        print("⚠️  Utilisation de distances estimées")
        for i in range(n):
            for j in range(n):
                if i != j:
                    distance_matrix[i][j] = (abs(i-j) * 50000) + 20000
        return distance_matrix

# ==================== DÉMARRAGE ====================

if __name__ == '__main__':
    print("🚀 Démarrage de l'API sur http://localhost:5000")
    print("📖 Testez avec: http://localhost:5000/health")
    if gmaps is None:
        print("⚠️  Google Maps non configuré - Distances estimées seront utilisées")
        print("💡 Ajoutez votre clé API Google Maps pour vraies distances")

    app.run(host='0.0.0.0', port=5000, debug=True)
