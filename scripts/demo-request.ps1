Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Body = @{
    config_name = "roundtable.example.yaml"
    scenario = @{
        title = "Island Control Wargame"
        background = "Blue force must seize and hold a contested island under time pressure."
        constraints = @(
            "Finish the main operation within 72 hours"
            "No external reinforcement"
        )
        friendly_forces = @(
            "Amphibious assault group"
            "Carrier-based aviation"
        )
        enemy_forces = @(
            "Coastal missile battalion"
            "Near-sea patrol ships"
        )
        objectives = @(
            "Secure the landing area"
            "Build a sustainable supply corridor"
        )
        victory_conditions = @(
            "Hold control within 72 hours"
            "Keep main force losses below the threshold"
        )
        additional_notes = @(
            "Intelligence has blind spots"
        )
    }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/discussions/run" `
    -ContentType "application/json" `
    -Body $Body
