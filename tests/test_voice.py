import unittest

from core.voice import _nettoyer_texte_pour_parole


class TestVoice(unittest.TestCase):
    def test_nettoyer_texte_pour_parole_enleve_les_markers_markdown(self):
        texte = '## Titre\n- **Ceci** est un *test* avec [lien](https://exemple.test) et __souligné__.'

        nettoye = _nettoyer_texte_pour_parole(texte)

        self.assertIn("Titre", nettoye)
        self.assertIn("Ceci", nettoye)
        self.assertIn("test", nettoye)
        self.assertIn("souligné", nettoye)
        self.assertNotIn("*", nettoye)
        self.assertNotIn("#", nettoye)
        self.assertNotIn("_", nettoye)
        self.assertNotIn("[", nettoye)
        self.assertNotIn("]", nettoye)
        self.assertNotIn("(", nettoye)
        self.assertNotIn(")", nettoye)


if __name__ == "__main__":
    unittest.main()
