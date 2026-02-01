import requests
import json

API_URL = "http://localhost:5000"

def test_health():
    """Test 1: Vérifier que l'API répond"""
    print("\n🧪 Test 1: Health check")
    response = requests.get(f"{API_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Réponse: {response.json()}")

def test_optimize():
    """Test 2: Optimisation avec IDs, filtrage et transporteur imposé"""
    print("\n🧪 Test 2: Optimisation complète")
    
    data = {
        "collectes": [
            {
                "ID_entree": "",
                "client": "",
                "adresse": "",
                "date_fixe": ""
            },
            {
                "ID_entree": "recJAWs87IXpc7Jtn",
                "client": "reczZWVsVtJYyn51O",
                "adresse": "Zone Industriel Route Les Ayvelles 08000 VILLERS-SEMEUSE",
                "date_flexible_debut": "2026-02-02",
                "date_flexible_fin": "2026-02-06"
            },
            {
                "ID_entree": "",
                "client": "",
                "adresse": "",
                "date_fixe": "",
                "transporteur": ""
            },
            {
                "ID_entree": "",
                "client": "",
                "adresse": "",
                "date_flexible_debut": "",
                "date_flexible_fin": "",
                "transporteur": ""
            }
        ],
        "livraisons": [
            {
                "ID_sortie": "",
                "client": "",
                "adresse": "",
                "date_fixe": ""
            },
            {
                "ID_sortie": "reckQdHvSCDKzQ45j",
                "client": "rechzmDFTs3HN4KlO",
                "adresse": "MRDPS chemin du bout de l'île 78840 FRENEUSE",
                "date_flexible_debut": "2026-02-02",
                "date_flexible_fin": "2026-02-06"
            }
        ],
        "Transits": [
            {
                "ID_transit": "",
                "matiere_transit": "",
                "adresse_depart": "",
                "adresse_arrivee": "",
                "date_fixe": ""
            },
            {
                "ID_transit": "rec01SbLOgEEekzM5",
                "matiere_transit": "SABLE DE FONDERIE",
                "adresse_depart": "EJ PICARDIE ZI de Marivaux 60149 SAINT-CREPIN-IBOUVILLERS",
                "adresse_arrivee": "Centre de traitement de Chalandry Elaire - Chemin vicinal n°1 La Garoterie 08160 CHALANDRY-ELAIRE",
                "date_flexible_debut": "2026-02-02",
                "date_flexible_fin": "2026-02-06"
            }
        ],
        "Transporteurs": [
            {
                "ID_transporteur": "rec5OjrckvJpHY40C",
                "client": "OMT BENNE",
                "adresse": "4 Rue du 19 Mars 1962 57300 Hagondange"
            },
            {
                "ID_transporteur": "recPCDj2YTpTEfNSX",
                "client": "LAMBERT",
                "adresse": "18 Rue du Haut Buisson 54120 Baccarat"
            },
            {
                "ID_transporteur": "recTfN97ddSLT5x2s",
                "client": "MAUFFREY LORRAINE NORD",
                "adresse": "Rue du Canal 57280 Hauconcourt"
            }
        ],
        "site_traitement": {
            "nom": "Site Longuyon",
            "adresse": "31 RUE FERNAND KAISER 54260 LONGUYON"
        },
        "contraintes": {
            "duree_max_en_heure": "12",
            "vitesse_moyenne_kmh": "70",
            "temps_operation_minutes": "30"
        }
    }
    
    response = requests.post(
        f"{API_URL}/optimize",
        json=data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {response.status_code}")
    print(f"\n📋 Résultat:")
    result = response.json()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if result.get('success'):
        stats = result.get('statistiques', {})
        transporteur = result.get('transporteur_optimal', {})
        
        print(f"\n📊 Résumé:")
        print(f"   ✅ Solution: {'Complète' if result.get('solution_complete') else 'Partielle'}")
        print(f"   📅 Date optimale: {result.get('date_optimale_formatee')}")
        print(f"   🚚 Transporteur: {transporteur.get('nom')} (ID: {transporteur.get('ID_transporteur')})")
        if transporteur.get('raison'):
            print(f"      Raison: {transporteur.get('raison')}")
        print(f"   🔄 Segments: {result.get('nombre_segments')}")
        print(f"   📏 Distance: {stats.get('distance_totale_km')} km")
        print(f"   ⏱️  Durée: {stats.get('duree_totale_heures')}h / {stats.get('duree_max_autorisee_heures')}h")
        print(f"   💰 Coût: {stats.get('cout_estime_euros')} €")
        print(f"   📦 Collectes: {stats.get('nombre_collectes_incluses')}/{stats.get('nombre_collectes_totales')}")
        print(f"   📦 Livraisons: {stats.get('nombre_livraisons_incluses')}/{stats.get('nombre_livraisons_totales')}")
        print(f"   🔄 Transits: {stats.get('nombre_transits_inclus')}/{stats.get('nombre_transits_totaux')}")
        print(f"   📊 Taux complétion: {stats.get('taux_completion')}")
        
        if result.get('transporteurs_alternatifs'):
            print(f"\n🔀 Autres transporteurs testés:")
            for alt in result['transporteurs_alternatifs']:
                print(f"      - {alt['nom']} (ID: {alt['ID_transporteur']}): {alt['distance_km']} km, {alt['duree_heures']}h, {alt['trajets_couverts']} trajets")
        
        if result.get('trajets_non_inclus'):
            print(f"\n⚠️  Trajets non inclus:")
            for trajet in result['trajets_non_inclus']:
                id_info = ""
                if trajet['type'] == 'collecte':
                    id_info = f"ID: {trajet.get('ID_entree', 'N/A')}"
                elif trajet['type'] == 'livraison':
                    id_info = f"ID: {trajet.get('ID_sortie', 'N/A')}"
                elif trajet['type'] == 'transit':
                    id_info = f"ID: {trajet.get('ID_transit', 'N/A')} - {trajet.get('matiere', '')}"
                print(f"      - {trajet['client']} ({trajet['type']}) [{id_info}]: {trajet['raison']}")

if __name__ == "__main__":
    print("🚀 Lancement des tests de l'API OR-Tools")
    print("=" * 70)
    
    try:
        test_health()
        test_optimize()
        print("\n✅ Tests terminés avec succès !")
    except requests.exceptions.ConnectionError:
        print("\n❌ Erreur: L'API n'est pas démarrée!")
        print("💡 Lancez d'abord: python app.py")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()