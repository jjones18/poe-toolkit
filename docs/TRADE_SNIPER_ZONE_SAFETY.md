# Trade Sniper zone safety

Trade Sniper enables **Only click while in a town or hideout** by default. It follows the active game's configured `Client.txt` and blocks both **Travel to Hideout** and **Teleport anyway** unless the most recent generated area is recognized as safe.

This is a separate hard gate from the normal post-click pause. Manual resume and the auto-resume timer cannot bypass an unsafe or unknown zone. Monitoring continues while blocked, and clicking is enabled automatically after Client.txt reports an allowed town or hideout.

## Fail-closed behavior

Clicks are blocked when:

- Client.txt is missing or not configured for the active game.
- No recent generated-area line can be found in the last 1 MiB of the log.
- The current internal area ID is not explicitly recognized.
- The current area is a campaign zone, map, boss area, special hub, or hideout-unlock map.

The service output reports `ZONE SAFE` or `ZONE BLOCKED` with the detected internal area ID and reason.

## PoE 1 towns

The allowlist includes one town for each of the ten acts plus both Epilogue towns:

- Act 1: `1_1_town`
- Act 2: `1_2_town`
- Act 3: `1_3_town`
- Act 4: `1_4_town`
- Act 5: `1_5_town`
- Act 6: `2_6_town`
- Act 7: `2_7_town`
- Act 8: `2_8_town`
- Act 9: `2_9_town`
- Act 10: `2_10_town`
- Oriath (Epilogue): `2_11_town`
- Karui Shores: `2_11_endgame_town`

## Hideouts

Real hideout instances use an internal ID beginning with `Hideout`. Trade Sniper requires that prefix at the beginning of the full ID. This safely rejects unlock maps such as `MapHideoutLimestone_Claimable` while supporting real hideout instances without relying on translated display names.

The default hideouts confirmed from the in-game Hideout Selection screenshots are:

- Alpine Hideout
- Backstreet Hideout
- Baleful Hideout
- Battle-scarred Hideout
- Cartographer’s Hideout
- Coastal Hideout
- Coral Hideout
- Desert Hideout
- Divided Hideout
- Enlightened Hideout
- Excavated Hideout
- Ghost-lit Graveyard Hideout
- Immaculate Hideout
- Lush Hideout
- Luxurious Hideout
- Nocturnal Hideout
- Overgrown Hideout
- Skeletal Hideout
- Stately Hideout
- Sunspire Hideout
- Undercity Hideout

Special or purchased hideouts are not maintained as a separate display-name list. They work when the game assigns the normal anchored `Hideout...` internal ID; an unusual special hideout with another form remains blocked until its Client.txt ID is reviewed and explicitly supported.

## PoE 2 compatibility

The same anchored hideout rule applies to PoE 2. Known campaign/endgame town IDs currently allowed are:

- `G1_town`, `G2_town`, `G3_town`, `G4_town`
- `C_G1_town`, `C_G2_town`, `C_G3_town`
- `P1_Town`, `P2_Town`, `P3_Town`
- `G_Endgame_Town`

Unknown future towns fail closed until their internal IDs are verified.

## Configuration

1. In Settings, select the active toolkit/game.
2. Set that game's Client.txt path.
3. Keep **Only click while in a town or hideout** checked in Trade Sniper.
4. Restart Trade Sniper after changing this setting or the Client.txt path.

The checkbox is persisted in the per-user `user_config.json`; it is never written to the checked-in legacy config.

## Timing and page reloads

- `Client.txt` is checked every 250 ms. After a safe area is logged, the controller pushes the new state to the page workers over local CDP; this is normally well under one second in total.
- A same-URL browser reload destroys the browser-resident worker even though the tab and search ID have not changed. The one-second controller lease heartbeat detects a missing worker and reinstalls it with the current zone state, cooldown, and confirmation timing.
- Periodic status reports count healthy current-run workers. If a tab is temporarily missing its worker, the report uses `healthy/tracked` form such as `Monitoring 5/6 tabs` until recovery.
