"""Shared complete bridge journey, now inside a CLI-created seller project."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import tests.test_journey as journey

class WorkspaceJourneyTests(TestCase):
    def test_setup_prospect_results_learn_resume_without_network_or_global_writes(self):
        with TemporaryDirectory() as directory:
            home=Path(directory)/'home';home.mkdir()
            with patch.dict(os.environ,{'HOME':str(home)}), patch('socket.socket',side_effect=AssertionError('Network forbidden')):
                journey.JourneyTests._journey(self,'codex-local',workspace=True)
            self.assertEqual(list(home.iterdir()),[])
