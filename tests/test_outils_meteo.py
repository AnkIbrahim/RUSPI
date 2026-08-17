import unittest
from unittest.mock import Mock, patch

from core.tools import obtenir_meteo


class TestOutilsMeteo(unittest.TestCase):
    @patch("core.tools.requests.get")
    def test_obtenir_meteo_retourne_phrase_en_francais(self, mock_get):
        geocoding_response = Mock()
        geocoding_response.status_code = 200
        geocoding_response.json.return_value = {
            "results": [{"latitude": 48.8566, "longitude": 2.3522}]
        }

        forecast_response = Mock()
        forecast_response.status_code = 200
        forecast_response.json.return_value = {
            "current_weather": {
                "temperature": 18.5,
                "weathercode": 2,
                "windspeed": 12.3,
            }
        }

        mock_get.side_effect = [geocoding_response, forecast_response]

        resultat = obtenir_meteo("Paris")

        self.assertIn("Paris", resultat)
        self.assertIn("18", resultat)
        self.assertIn("partiellement nuageux", resultat)
        self.assertIn("12", resultat)


if __name__ == "__main__":
    unittest.main()
