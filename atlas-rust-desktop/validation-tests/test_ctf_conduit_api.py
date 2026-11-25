"""Contract tests for Atlas CTF Swarm room API and Conduit state/devlog persistence."""

import tempfile
import unittest

import no_real_keys  # noqa: F401
import ctf_conduit_api


class TestCtfSwarmRooms(unittest.TestCase):
    def setUp(self):
        ctf_conduit_api.reset_swarm_rooms_for_tests()

    def test_join_claim_note_archive_focus_and_leave(self):
        snap = ctf_conduit_api.handle_swarm_event(
            "Atlas Alpha!!",
            {
                "type": "room:join",
                "sessionId": "sess-1",
                "uid": "u1",
                "handle": "tester",
                "role": "admin",
                "activeView": "curriculum",
            },
        )
        self.assertEqual(snap["roomId"], "atlasalpha")
        self.assertEqual(len(snap["peers"]), 1)
        self.assertEqual(snap["peers"][0]["handle"], "tester")

        # Claim target
        snap = ctf_conduit_api.handle_swarm_event(
            "atlasalpha",
            {
                "type": "claim:toggle",
                "sessionId": "sess-1",
                "handle": "tester",
                "role": "admin",
                "challengeId": "nm-03-strings-lab",
            },
        )
        self.assertIn("nm-03-strings-lab", snap["claims"])

        # Shared note
        snap = ctf_conduit_api.handle_swarm_event(
            "atlasalpha",
            {
                "type": "note:sync",
                "sessionId": "sess-1",
                "handle": "tester",
                "challengeId": "nm-03-strings-lab",
                "content": "Found flag in .rodata",
            },
        )
        self.assertEqual(snap["sharedNotes"]["nm-03-strings-lab"]["content"], "Found flag in .rodata")

        # Archive manifest
        snap = ctf_conduit_api.handle_swarm_event(
            "atlasalpha",
            {
                "type": "archive:share",
                "sessionId": "sess-1",
                "handle": "tester",
                "role": "admin",
                "fileName": "Nightmare.zip",
                "fileCount": 2,
                "paths": ["03-strings/strings_lab.bin", "03-strings/README.md"],
            },
        )
        self.assertEqual(snap["archiveManifest"]["fileName"], "Nightmare.zip")

        # Focus broadcast
        snap = ctf_conduit_api.handle_swarm_event(
            "atlasalpha",
            {
                "type": "focus:broadcast",
                "sessionId": "sess-1",
                "handle": "tester",
                "role": "admin",
                "challengeId": "nm-04-bof-variable",
            },
        )
        self.assertEqual(snap["lastFocus"]["challengeId"], "nm-04-bof-variable")

        rooms = ctf_conduit_api.list_swarm_rooms()["rooms"]
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["claimCount"], 1)
        self.assertTrue(rooms[0]["hasArchive"])

        # Leave releases claim
        snap = ctf_conduit_api.handle_swarm_event(
            "atlasalpha",
            {"type": "room:leave", "sessionId": "sess-1"},
        )
        self.assertEqual(len(snap["peers"]), 0)
        self.assertEqual(len(snap["claims"]), 0)


class TestConduitPersistence(unittest.TestCase):
    def test_state_and_devlog_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ctf_conduit_api.read_conduit_state(tmp)["state"])
            ctf_conduit_api.write_conduit_state(tmp, {"version": 1, "activeView": "overview"})
            self.assertEqual(ctf_conduit_api.read_conduit_state(tmp)["state"]["activeView"], "overview")
            ctf_conduit_api.reset_conduit_state(tmp)
            self.assertIsNone(ctf_conduit_api.read_conduit_state(tmp)["state"])

            res = ctf_conduit_api.append_devlog(
                tmp,
                {
                    "title": "Atlas CTF Integrated",
                    "authorHandle": "@tester",
                    "targetHandle": "@all-agents",
                    "branch": "integrate_nightmare_auth_ctf",
                    "summary": "Mounted CTF, Conduit, and Workflows tabs.",
                    "files": ["atlas-rust-desktop/src/App.tsx"],
                },
            )
            self.assertTrue(res["ok"])
            self.assertIn("Atlas CTF Integrated", res["content"])
            self.assertIn("atlas-rust-desktop/src/App.tsx", ctf_conduit_api.read_devlog(tmp)["content"])


if __name__ == "__main__":
    unittest.main()
