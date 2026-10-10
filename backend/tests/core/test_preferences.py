"""Public preferences must match their generated contract on the wire."""


def test_profile_defaults_are_complete_without_changing_saved_preferences(h):
    expected = {
        "reduced_motion": False,
        "notifications": True,
        "world_daylight": False,
        "sound_enabled": False,
        "auto_camera": True,
        "graphics_quality": None,
    }
    for path in ("/me", "/settings"):
        assert h.get(path)["profile"]["preferences"] == expected
    assert h.scalar("SELECT preferences_json FROM profiles") == "{}"


def test_partial_preferences_keep_explicit_false_and_responsive_quality(h):
    profile = h.get("/me")["profile"]
    saved = h.patch("/settings", {"auto_camera": False, "expected_version": profile["version"]})
    assert saved["preferences"]["auto_camera"] is False
    assert saved["preferences"].get("notifications") is True
    assert saved["preferences"]["graphics_quality"] is None
    for path in ("/me", "/settings"):
        assert h.get(path)["profile"]["preferences"] == saved["preferences"]
    assert h.scalar("SELECT preferences_json FROM profiles") == '{"auto_camera":false}'
    again = h.patch("/settings", {"graphics_quality": "low", "expected_version": saved["version"]})
    assert again["preferences"]["graphics_quality"] == "low"
    assert again["preferences"]["auto_camera"] is False
