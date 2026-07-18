import os
import unittest

from dotenv import load_dotenv


class TestGeminiIntegration(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RUN_INTEGRATION_TESTS") == "1",
        "Set RUN_INTEGRATION_TESTS=1 to run live Gemini checks.",
    )
    def test_live_gemini_generation(self):
        from google import genai

        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY")
        self.assertTrue(api_key, "GEMINI_API_KEY is required for live Gemini checks")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents="Reply with the word OK.",
        )
        self.assertIn("OK", response.text.upper())


if __name__ == "__main__":
    unittest.main()
