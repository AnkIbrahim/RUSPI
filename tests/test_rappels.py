import json
import tempfile
import unittest
from pathlib import Path

from core import rappels


class TestRappels(unittest.TestCase):
    def setUp(self):
        self.dossier_temp = tempfile.TemporaryDirectory()
        self.chemin = Path(self.dossier_temp.name) / "rappels.json"
        self.original_chemin = rappels.CHEMIN_FICHIER_RAPPELS
        rappels.CHEMIN_FICHIER_RAPPELS = self.chemin
        rappels._sauvegarder_rappels([])

    def tearDown(self):
        rappels.CHEMIN_FICHIER_RAPPELS = self.original_chemin
        self.dossier_temp.cleanup()

    def test_ajouter_rappel_persiste_et_retourne_confirmation(self):
        message = rappels.ajouter_rappel("Prendre un médicament", "09:30")

        self.assertIn("Prendre un médicament", message)
        self.assertIn("09:30", message)

        donnees = json.loads(self.chemin.read_text(encoding="utf-8"))
        self.assertEqual(len(donnees), 1)
        self.assertEqual(donnees[0]["texte"], "Prendre un médicament")
        self.assertEqual(donnees[0]["statut"], "en_attente")

    def test_verifier_rappels_en_attente_marque_comme_declenche(self):
        rappel = {
            "texte": "Rappel test",
            "heure": "00:00",
            "date_rappel": "2000-01-01T00:00:00",
            "statut": "en_attente",
        }
        self.chemin.write_text(json.dumps([rappel], ensure_ascii=False), encoding="utf-8")

        resultats = rappels.verifier_rappels_en_attente()

        self.assertEqual(resultats, ["Rappel test"])
        donnees = json.loads(self.chemin.read_text(encoding="utf-8"))
        self.assertEqual(donnees[0]["statut"], "déclenché")


if __name__ == "__main__":
    unittest.main()
