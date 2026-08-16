from scripts.validate_discord_live_stage02 import installation_prompt


def test_existing_bot_guidance_checks_before_offering_duplicate_install() -> None:
    prompt = installation_prompt(
        label="Guild B",
        link="https://discord.example/install",
        reinstall=False,
    )

    assert "already present" in prompt
    assert "do not install it again" in prompt
    assert "Check Discord status" in prompt
