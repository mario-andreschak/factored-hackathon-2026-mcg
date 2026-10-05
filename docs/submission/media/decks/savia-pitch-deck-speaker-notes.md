# Savia — Short Pitch — speaker notes

All customer examples are fictional. Source-data counts refer to the organizer-supplied synthetic snapshot; no live bank action is claimed.

## Slide 1: Ask once. Carry on.

Meet Savia: ask once, carry on. The home scene is an illustrative fictional customer image for the TV spot, not a service screenshot. Savia's product promise is to keep the question moving, bring useful perspectives back, and remember the thread.

## Slide 2: A grounded answer, in the moment.

Actual grounded answer captured in docs/submission/measurements/team-story-final/04-grounded-answer.png. The selected model answer was useful and took 9.338 seconds. It described the existing fictional claim and current review status; it did not create another claim. The informational team interaction completed in 4.278 seconds. Keep these separate from the standalone two-worker stdio MCP smoke, which completed in 2.783 seconds. No real bank decision or action is claimed.

## Slide 3: Your team’s suggestions stay with you.

Actual saved-result capture in docs/submission/measurements/team-story-final/11-saved-useful-result.png. The customer explicitly confirmed the answer was helpful and closed the informational inquiry. Both Savia-team suggestions stayed visible after a new chat and reload. The bank claim was an existing simulated record and was not newly created. The UI team interaction completed in 4.278 seconds; the selected grounded model answer took 9.338 seconds. The 2.783-second MCP smoke was a separate standalone run.

## Slide 4: A voice that keeps your place.

Accepted actual integrated Savia UI capture, source 9d77a7599128b668b0e34f9c2937eb40b6bd3824, image sha256 484fe8edc07ac37dd78f61deb7a08254352b8ce597fa8265f917706e93d199a5, served JS hash f06ecbad1ea5089a227a04ea7468aeb8f4b1ef023ac04a98e6b71379771cc8bd. Foreground Spanish transcript: “Despacio, sí, bien tranquilo, aquí estoy.” (6.6 s; exact 158,400 samples), full browser playback acknowledged once with HTTP 200 at 21.473 s. The existing third informational inquiry was marked helpful at 14.949 s during the foreground playback. Its canonical closure was available at 15.836 s and queued until native request 21.503 s. Closure transcript: “Cerró la consulta, ya te ayudó la explicación.” (3.95 s; exact 94,800 samples), acknowledged once with HTTP 200 at 26.659 s. This is an informational helpful closure, not a bank decision or refund. Existing case context, two completed team suggestions and prior bank reply were restored; the continuation created zero bank chats, inquiries or workers. No additional worker concurrency or spoken recommendations are claimed. Input used typed Spanish plus a file-backed fictional WAV through the browser control; the physical microphone is unqualified and raw final ASR contained errors. Optional recorder cleanup exceeded its 180-second cap while awaiting unused response bodies after both playback receipts and required product checks passed; its diagnostic exit 1 is not a product failure. Evidence: docs/submission/measurements/intended-savia-native/receipt.json.

## Slide 5: Let’s prove value with a bounded pilot.

Close with the invitation for a bank partner to run a bounded customer-support pilot. The value hypothesis is fewer repeat contacts and clearer context for support; this deck claims no ROI or measured reduction. Agree measures for repeat contacts, time to first useful answer, customer helpful closure and handoff quality. Use a fictional, informational scope and no production actions. The canonical browser path uses the Savia app host loop for two direct-provider tasks; it is separate from optional generic FLUJO/MCP scheduling. The latter's qualification made one connected call against empty informational state, queued no case, made no paid model call, and left its installed 30-minute schedule disabled. The 2.783-second standalone MCP smoke is also separate from the browser answer and team UI times. Evidence: docs/submission/runtime-mcp.json.
