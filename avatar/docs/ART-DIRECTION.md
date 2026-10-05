# Elsewhere art direction

Elsewhere is an interactive film around a working voice companion. The world is a place to inhabit during the task, and the character responds to the visitor before, during, and after a reply. The three companions are original designs; no existing film character or branded avatar is used.

## Moss: a living painting

Moss is an ancient turtle with a kind, sloth-like face, amber eyes, a moss shell, ferns, and a miniature tree growing on his back. He rests on the left side of a wide environment. The right side contains water or an open clearing, so the visible browser can inhabit the world as a reflecting pond.

Ten separate original cinematic paintings were generated with the **built-in imagegen tool**, one call per final asset. The first painting supplied the character and style reference for the remaining nine. Original tool outputs remain under the Codex generated-images directory. Final project assets are committed at `avatar/public/scenes/01-pond-sanctuary.webp` through `10-homecoming-sunset.webp`. Each is 1672 × 941 pixels, approximately 16:9, converted to WebP at quality 88 with Pillow. This conversion only encodes the finished pixels; it does not alter the creative content.

Moss is animated inside the actual painted scene, rather than placing a second character over him. `MossPuppet.tsx` maps an elliptical body, neck/head, eye, and mouth rig to every painting. Its Three.js fragment shader drives local shell expansion, torso and tree-weight sway, neck motion, thoughtful inclination, pointer-following attention, eye blinks, iris gaze, and an audio-driven mouth opening with a following jaw. The surrounding river has its own flow displacement. The effect is intentionally restrained: a heavy old creature breathes and takes his time. This is image-based puppetry, not a fully articulated skeletal model or phoneme-level lip rig.

Scene changes run a 4.8-second camera glide and crossfade, with a gentle torso walking rhythm during travel. The app controls the story destination through `sceneIndex`; the world handles the cinematic arrival. Ambient fireflies, pollen, fog, rain, reflected water, and warm attention light sit in independent layers.

## Orbit: the observatory

Orbit is a porcelain and brushed-brass companion with a dark visor, luminous eyes, and a small speaking light. A teal observatory has nested celestial rings, sculptural columns, a raised circular platform, suspended dust, and a physical console on the right. The direct Three.js rig breathes, glances toward the pointer, inclines its head while thinking, blinks, moves its mouth with speech, and changes rim light with voice energy. Gestures stay measured.

## Spark: the desert roadside garage

Spark is an original expressive road companion with an oversized felt hat, brass goggles, a teal feather, amber eyes, swept hair, a rust canvas jacket, scarf, toolkit, and a quick grin. His world contains a dusty road, canyon silhouettes, cacti, vintage fuel pumps, a canopy with a neon edge, and a visible console.

The primary Spark character is a locally authored Blender model, exported as `public/models/spark.glb`. Its 20-joint skeleton carries independent `Idle`, `Talk`, and `Gesture` clips. Speech blends skeletal gestures and an audio-driven `MouthOpen` morph; `BlinkL`/`BlinkR` morphs and pointer gaze keep him attentive. The self-contained 3.44 MB asset uses 25 mesh primitives and standard PBR materials. The renderer retains the earlier procedural character as its loading/failure fallback. The editable compressed `.blend` and a 1200px local Cycles portrait are under `assets/spark/`; the reproducible background CLI pipeline is documented in [tools/blender/README.md](../tools/blender/README.md). No cloud renderer or external mesh source was used. These are envelope-based mouth movements, not phoneme-aligned lip sync.

The requested Hessi James reference was interpreted as an energetic conversational rhythm: a fast verbal torrent in a western roadside setting. The short-film distributor describes the desert-western setup at [Hessi James, Kurzfilm Verleih](https://verleih.shortfilm.com/films/hessi-james). Spark is an independent human character and scene, not a replica of that film's bug characters.

## Runtime contract and resilience

Import the default component from `avatar/src/world/World.tsx`. It accepts `avatar: 'moss' | 'orbit' | 'spark'`, `sceneIndex: number`, `phase: 'idle' | 'listening' | 'thinking' | 'speaking'`, `audioLevel: number` (0–1), `reducedMotion: boolean`, and `pointer: { x: number; y: number }` (centered, normally −1 to 1). Pointer values may be mutated in place; both character render loops read the current values on each frame. `SCENES` exports names, places, weather, image paths, and accent tints for the app's controls.

The world supplies atmosphere and physical scenery; the app mounts the real browser, captions, consent controls, and voice controls above it. The world is decorative and marked aria-hidden, leaving accessible interaction to the app layer.

Renderers cap device pixel ratio, reuse frame objects, release geometries/materials/textures/shadow maps, cancel animation frames on unmount, and pause when the page is hidden. WebGL initialization/context-loss failures use a painted Moss backdrop or a CSS character for Orbit/Spark. Failed artwork loads preserve the last successfully loaded painting. Reduced motion suppresses breathing, scenery drift, camera travel, autonomous gestures, and pointer parallax; direct voice/state responses remain visible. Only the next Moss painting is preloaded by the app layer. No model files, shader libraries, textures, fonts, or 3D assets are downloaded from third-party CDNs at runtime.

## Final generation prompt set

Each following prompt generated exactly one final scene with `transparent_background: false`. Prompts 2–10 referenced the first finished painting for character and style consistency.

### 1. Pond sanctuary

```text
Use case: illustration-story. Asset type: fullscreen 16:9 cinematic painted background for an interactive voice companion. Generate one finished original environment, not a contact sheet. Scene: an intimate ancient forest pond sanctuary at blue hour, crystal reflecting water across lower right foreground, huge fern leaves and mossy roots at edges, mist between towering trees, scattered fireflies, a tiny amber lantern. Subject: one gentle ancient moss turtle with a sloth-like kind face, small luminous amber eyes, rounded moss-covered shell carrying a miniature tree and lush ferns. Turtle resting on a stone island at center left, its whole silhouette clearly seen, calm wise presence, not a monster. Composition: expansive wide 16:9 cinematic shot; turtle occupies left central third, magical reflecting pond lower-right is uncluttered enough for an interface overlay; keep top third atmospheric and clear. Style: exceptionally beautiful hand-painted Japanese fantasy animation background, watercolor and gouache, expressive brushwork and detailed organic nature, original character design, rich deep teal and emerald greens, warm glowing amber accents. Lighting: soft moody twilight with volumetric shafts and ethereal atmosphere. No text, no UI, no laptop, no modern machinery, no frame, no watermark.
```

### 2. Lantern grove

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted scene for an interactive companion. Primary request: Lantern grove: an ancient giant woodland grove at evening with amber paper lanterns hanging among immense roots, small flower-filled stream and reflecting pool lower right, gentle moss turtle walking slowly along a root bridge at center left. Warm lantern glow and emerald twilight. No people. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 3. Rainy canopy

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted scene for an interactive companion. Primary request: Rainy canopy: tranquil deep forest during soft rain, huge translucent leaves overhead with droplets, turquoise reflecting pool lower right, gentle moss turtle sheltering beneath an ancient leaning tree at center left. Misty layered canopy, blue-green rain and warm amber light from turtle eyes. Atmospheric wet moss and beautiful rain. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 4. Cliff sunrise

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted scene for an interactive companion. Primary request: Cliff sunrise: airy high cliff above a sea of pale peach clouds, layered distant mountains and graceful trees, gentle moss turtle resting at center left, shallow reflecting pool lower right beside cliff and stone path. Magnificent delicate sunrise, gold rim light on its little tree and ferns, peaceful sense of possibility. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 5. River crossing

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: River crossing: a broad sparkling forest river with wide ancient mossy stepping stones, arching willow branches and layered soft green woods, shallow quiet reflecting pool lower right, gentle moss turtle with a miniature tree walking carefully across a stepping stone at center left. Delicate early morning beams, fresh jade water, amber light, adventurous yet reassuring. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 6. Moonlit lake

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: Moonlit lake: a vast silent forest lake under a luminous full moon, deep indigo sky and silver-blue clouds, fireflies and hanging willow leaves, gentle moss turtle with a miniature tree resting on lake shore at center left. Crystal flat silver reflecting water lower right is clear. A small warm lantern beside turtle, mystical tender midnight calm. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 7. Old ruins

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: Old ruins: soft overgrown ancient stone arch and forgotten terraced temple half reclaimed by a flourishing forest, moss, ferns, tiny flowers, sun shafts through roofless arches. Gentle moss turtle with a miniature tree at center left, an elegant reflecting stone basin lower right. Peaceful moss-green and weathered pale stone, wise timeless atmosphere. No people. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 8. Meadow

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: Meadow: expansive luminous meadow of delicate wildflowers among ancient huge graceful trees, sunlit dust and rolling green hills into distance. Gentle moss turtle with a miniature tree and lush fern shell resting in wildflowers at center left, a small natural reflecting pond lower right. Warm spring afternoon, pale blue sky, verdant honey-gold calm and openness. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 9. Floating islands

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: Floating islands: beautiful ancient garden islands suspended above lavender and peach clouds, distant floating gardens connected by curling tree roots, waterfalls trailing into mist. Gentle moss turtle with a miniature tree standing safely on broad grassy island at center left, natural tranquil reflecting pond lower right. Dreamlike but delicate and believable painted fantasy, soft afternoon celestial light, expansive wonder. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```

### 10. Homecoming sunset

```text
Use case: illustration-story. Asset type: one finished fullscreen 16:9 cinematic painted environment for an interactive companion. Primary request: Homecoming sunset: a welcoming ancient mossy cottage built into the enormous roots of a tree beside a glowing lake, tiny warm window lights and a stone footpath across ferns. Gentle moss turtle with a miniature tree beside the cottage at center left, reflecting pond lower right. Golden peach sunset and lavender shadows, safe tender feeling of resolution and home. Input image role: character design and visual style reference only, create a new scene. Subject invariant: ancient gentle turtle with kind sloth-like face, tiny amber eyes, substantial round moss shell carrying a miniature leafy tree and lush ferns, original fantasy companion called Moss. Keep character consistent with reference, whole silhouette visible on left central third and small relative to the grand environment. Style: exquisite hand-painted Japanese fantasy animation background, watercolor and gouache organic brushwork, rich visual depth and detailed botany. Composition: widescreen 16:9, low foreground pond on right remains visually clear for live browser overlay, plenty of atmospheric space in upper third. No text, no UI, no laptop, no modern technology, no watermark, no framing border.
```
